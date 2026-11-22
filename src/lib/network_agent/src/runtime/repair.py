"""Graph B's judgement and local repairs (step 7): triage, plan_local_repair, execute_repair, report_deviation.

The two judgements (the ◇ nodes of graph B) sit behind ``RuntimePolicy``; ``RulePolicy`` is the first,
rule-based version, and build_runtime_graph takes another in its place.

    triage   finishes_in_reservation (p95 of the remaining bytes is within the reservation's end) → nothing to do;
             same failed repair conditions and retry not yet due → defer; otherwise → repair
    plan_local_repair
             which repairs are worth trying, in order (smallest change first):

        extend      propose a later end within the request deadline; execute only after scheduler approval
        increase    use free capacity on the same path, preserving the existing completion promise
        reroute     preserve endpoints and completion promise; avoid damaged shared links, respect the
                    cooldown, prepare a new circuit, confirm the transfer switch, then release the old one
        borrow      propose complete reallocations on an isolated ledger; the scheduler selects one whole
                    plan, which is revalidated before any lender or target is changed

             which ones fit which deviation (detection.py):
                 slow, a hop down or squeezed now     extend, reroute (+ borrow if squeezed and shared)
                 slow, path healthy (unlocated)       extend only: utilization, not capacity
                 overrun, or damage ahead (link)      extend, increase, reroute (+ borrow unless down)
             increase sends more before the damaged slots, so it needs them to be ahead; borrow needs a
             lower-priority circuit of ours on a squeezed hop (on any hop of the path for an overrun)

Unlocated slowdowns are not proof of a host bottleneck. They conservatively receive an extension
proposal; autonomous rate/path changes require evidence that network resources can improve throughput.
Approvals and transfer handoffs use provisional adapters. A missing adapter never grants permission.
Failed approval or execution advances to the next repair; exhausting the list reports unresolved.
Multi-circuit rollback is best effort: any lender that could not be restored is explicitly reported.
Configuration success and a handoff acknowledgement do not prove sustained throughput recovery;
subsequent telemetry/ticks reassess progress. All state changes reuse graph A's operations.

"""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal, Protocol

from ..adapters.sense import SenseError, cancel_instances
from ..context.context import AgentContext, Committed, FailedRepair, RepairConditions, Reservation, ReservedOffer
from ..models.schemas import Cause, Commitment, DeviationReport, RepairAction, TimeWindow, TransferRequest
from ..planning.placement import Placement, bytes_at, search
from ..shared.operations import modify_held, open_circuit, record_change
from ..state.ledger import EPS_GBPS, InsufficientCapacity
from .assessment import Assessment, expected_gbps, expected_rates_on_circuit, finish_under
from .forecast import refresh
from .negotiation import Modification, approve, candidate

TriageVerdict = Literal["finishes_in_reservation", "retry_deferred", "repair"]
NOTHING_TO_TRY = "no repair can get the remaining bytes through by the deadline"
Step = Literal["extend", "increase", "reroute", "borrow"]


@dataclass(frozen=True)
class RepairPlan:
    assessment: Assessment
    steps: list[Step]                                 # in the order to try; empty: nothing is worth trying


@dataclass(frozen=True)
class RepairResult:
    """What repairing did to one commitment: repaired (how), or unresolved (why). A lower-priority
    commitment that lent rate is also a result: repaired, action "lend"."""

    commitment: Commitment                            # updated if repaired, as it stands if not
    request: TransferRequest
    cause: Cause
    links: tuple[str, ...]
    outcome: Literal["repaired", "unresolved"]
    action: RepairAction | None
    finish: tuple[datetime, datetime] | None          # (p50, p95)
    lent_to: str | None = None
    tried: tuple[str, ...] = ()                       # unresolved: why each step failed


@dataclass(frozen=True)
class Triage:
    """triage's sorting of the assessments into three groups."""

    finishes_in_reservation: list[str]  # commitment ids: the rest still gets through by the reservation's end
    retry_deferred: list[str]           # unchanged failed repair, retry not yet due
    to_repair: list[Assessment]         # the rest, passed on to plan_local_repair
    conditions: dict[str, RepairConditions]
    refreshed: list[str]


class RuntimePolicy(Protocol):
    def triage(self, ctx: AgentContext, assessment: Assessment, conditions: RepairConditions | None,
               now: datetime) -> TriageVerdict: ...
    def plan_local_repair(self, ctx: AgentContext, assessment: Assessment, now: datetime) -> list[Step]: ...


class RulePolicy:
    """The first, rule-based policy (see the module docstring)."""

    def triage(self, ctx: AgentContext, assessment: Assessment, conditions: RepairConditions | None,
               now: datetime) -> TriageVerdict:
        if assessment.finishes_in_reservation:
            return "finishes_in_reservation"
        failed = ctx.failed_repairs.get(assessment.commitment_id)
        if failed is not None and failed.conditions == conditions and now < failed.retry_after:
            return "retry_deferred"
        return "repair"

    def plan_local_repair(self, ctx: AgentContext, assessment: Assessment, now: datetime) -> list[Step]:
        reserved_offer = assessment.committed.reserved_offer
        request = reserved_offer.request
        deviation = assessment.deviation
        candidate_paths = ctx.topology.paths(request.src, request.dst, ctx.cfg.max_paths)
        best_gbps = max(_path_capacity(ctx, path) for path in candidate_paths)
        if assessment.cap_gbps is not None:
            best_gbps = min(best_gbps, assessment.cap_gbps)
        seconds_left = (assessment.deadline - now).total_seconds()
        if seconds_left <= 0 or bytes_at(best_gbps, seconds_left) < assessment.remaining_bytes:
            return []
        if assessment.cap_gbps is not None:           # slow with a healthy path: low utilization, not capacity
            return ["extend"]
        steps: list[Step] = ["extend"]
        current_path = reserved_offer.placement.path
        damaged_now = deviation.slow and deviation.cause in ("link_down", "congestion")
        if (not damaged_now                           # the damage is now: there is no "before" to send more in
                and reserved_offer.placement.gbps + ctx.cfg.rate_step_gbps <= _path_capacity(ctx, current_path) + EPS_GBPS):
            steps.append("increase")
        if any(path != current_path for path in candidate_paths):
            steps.append("reroute")
        if (deviation.cause != "link_down"            # a down hop gives every circuit 0: nothing to borrow
                and _lenders(ctx, assessment, now, cannot_lend=set(ctx.reported_unresolved))):
            steps.append("borrow")
        return steps


# ── triage and plan_local_repair ──────────────────────────────────────────

def forget_changed_commitments(ctx: AgentContext) -> None:
    """Run even when detection finds no deviations, so releases and modifications clear old failures."""
    for commitment_id, failed in list(ctx.failed_repairs.items()):
        if ctx.commitments.get(commitment_id) != failed.conditions.commitment:
            ctx.forget_repair(commitment_id)
    for commitment_id, commitment in list(ctx.repair_constraint_commitments.items()):
        if ctx.commitments.get(commitment_id) != commitment:
            ctx.repair_deadlines.pop(commitment_id, None)
            del ctx.repair_constraint_commitments[commitment_id]
    for commitment_id in list(ctx.last_reroute):
        if commitment_id not in ctx.commitments:
            del ctx.last_reroute[commitment_id]


def repair_conditions(ctx: AgentContext, assessment: Assessment, now: datetime) -> tuple[RepairConditions, list[str]]:
    """Read current and candidate paths before deduplication, including capacity needed by possible lenders.

    Slot indices keep time windows distinct; sampling/expiry timestamps do not turn identical capacity
    into a new condition. The retry timer covers external changes not observable here (e.g. SENSE recovery).
    """
    offer = assessment.committed.reserved_offer
    request = offer.request
    paths = tuple(dict.fromkeys([offer.placement.path,
                                *ctx.topology.paths(request.src, request.dst, ctx.cfg.max_paths)]))
    lenders = _lenders(ctx, assessment, now, cannot_lend=set())
    spans = [(path, now, assessment.deadline) for path in paths]
    spans += [(lender.reserved_offer.placement.path, now, lender.reserved_offer.request.window.latest_finish)
              for lender in lenders]
    refreshed = refresh(ctx, spans, now).refreshed
    slots = set()
    for path, start, end in spans:
        start, end = max(start, ctx.ledger.origin), min(end, ctx.ledger.horizon_end)
        if start < end:
            slots.update((link, slot) for link in path for slot in ctx.ledger.slots_covering(start, end))
    capacity = tuple((link, slot, ctx.ledger.observed(link, slot).up,
                      ctx.ledger.observed(link, slot).gbps, ctx.ledger.own(link, slot))
                     for link, slot in sorted(slots))
    lender_state = tuple((lender.commitment, lender.reserved_offer.request,
                          _remaining_bytes(ctx, lender.reserved_offer, now),
                          lender.commitment.commitment_id in ctx.reported_unresolved)
                         for lender in lenders)
    last = ctx.last_reroute.get(assessment.commitment_id)
    ready = last is None or (now - last).total_seconds() >= ctx.cfg.reroute_cooldown_seconds
    return RepairConditions(assessment.deviation.cause, assessment.deviation.links, assessment.committed.commitment, request,
                            assessment.remaining_bytes, assessment.cap_gbps, assessment.deadline, ready,
                            paths, capacity, lender_state), refreshed


def triage_all(ctx: AgentContext, policy: RuntimePolicy, assessments: list[Assessment], now: datetime) -> Triage:
    """Compare repair inputs independently of what has already been reported."""
    triaged = Triage([], [], [], {}, [])
    for assessment in assessments:
        conditions = None
        if not assessment.finishes_in_reservation:
            conditions, refreshed = repair_conditions(ctx, assessment, now)
            triaged.conditions[assessment.commitment_id] = conditions
            triaged.refreshed.extend(refreshed)
        verdict = policy.triage(ctx, assessment, conditions, now)
        if verdict == "finishes_in_reservation":
            ctx.forget_repair(assessment.commitment_id)
            triaged.finishes_in_reservation.append(assessment.commitment_id)
        elif verdict == "retry_deferred":
            triaged.retry_deferred.append(assessment.commitment_id)
        else:
            triaged.to_repair.append(assessment)
    return triaged


def plan_all(ctx: AgentContext, policy: RuntimePolicy, to_repair: list[Assessment], now: datetime) -> list[RepairPlan]:
    """A plan per commitment, highest priority first (ties in commitment order)."""
    by_priority = sorted(to_repair, key=lambda assessment: -assessment.priority)
    return [RepairPlan(assessment, policy.plan_local_repair(ctx, assessment, now)) for assessment in by_priority]


# ── execute ───────────────────────────────────────────────────────────────

def unresolved_result(assessment: Assessment, tried: tuple[str, ...]) -> RepairResult:
    deviation = assessment.deviation
    return RepairResult(deviation.committed.commitment, deviation.committed.reserved_offer.request, deviation.cause,
                        deviation.links, "unresolved", None, assessment.finish_if_kept, tried=tried)


def execute(ctx: AgentContext, plans: list[RepairPlan], now: datetime) -> list[RepairResult]:
    """Try each plan's steps in order, plans in the given (priority) order. Commitments being repaired in
    this run, or waiting for the scheduling agent, do not lend."""
    cannot_lend = {plan.assessment.commitment_id for plan in plans} | set(ctx.reported_unresolved)
    results: list[RepairResult] = []
    for plan in plans:
        assessment = plan.assessment
        tried: list[str] = []
        for step in plan.steps:
            current = next((c for c in ctx.committed() if c.commitment.commitment_id == assessment.commitment_id), None)
            if current != assessment.committed:
                # Never execute the rest of an old plan after a concurrent protocol modification.
                if current is not None:
                    results.append(replace(unresolved_result(assessment, tuple(tried) + (
                        "commitment changed during repair; re-evaluate on the next event",)),
                        commitment=current.commitment, request=current.reserved_offer.request, finish=None))
                break
            assessment = replace(assessment, deadline=min(assessment.deadline,
                ctx.repair_deadlines.get(assessment.commitment_id, assessment.deadline)))
            step_results, failure = REPAIR_STEPS[step](ctx, assessment, now, cannot_lend)
            results += step_results
            if failure is None:
                break
            tried.append(f"{step}: {failure}")
        else:
            results.append(unresolved_result(plan.assessment, tuple(tried) or (NOTHING_TO_TRY,)))
    return results


# A repair step returns (results for the commitments it changed, why it failed); failure is None once repaired.
StepAttempt = tuple[list[RepairResult], str | None]


def _reservation_and_offer_now(ctx: AgentContext, committed: Committed) -> tuple[Reservation, ReservedOffer]:
    """The reservation and reserved offer as they are now (an earlier repair in this run may have changed them)."""
    reservation = ctx.reservations[committed.reserve_id]
    offer_id = committed.reserved_offer.offer_id
    return reservation, next(held for held in reservation.held if held.offer_id == offer_id)


def _path_capacity(ctx: AgentContext, path) -> float:
    return min(ctx.topology.links[link].capacity_gbps for link in path)


def _ceil_to_second(moment: datetime) -> datetime:
    return moment if not moment.microsecond else moment.replace(microsecond=0) + timedelta(seconds=1)


def _placement_through_by(ctx: AgentContext, reserved_offer: ReservedOffer, gbps: float, nbytes: int,
                          deadline: datetime, cap: float | None, now: datetime) -> Placement | None:
    """
    - If this already booked offer is changed to a given rate, at what time should 
    the reserve be opened to transfer the remaining bytes? 
    - It returns the modified new placement; 
    - If the data cannot be uploaded by the deadline, return None.
    - nbytes: remaining bytes
    """
    placement = reserved_offer.placement

    # Based on the ledger prediction, how much throughput can this stream achieve in each time period 
    # from now until the deadline?
    spans = expected_rates_on_circuit(ctx.ledger, placement.path, gbps, max(now, placement.start), deadline,
                                      reserved_offer.booking_id, cap)

    finish = ctx.rate_model.finish_at_expected_rates(spans, nbytes)
    if finish is None or finish[1] > deadline:
        return None
    return replace(placement, gbps=gbps, end=max(placement.end, min(_ceil_to_second(finish[1]), deadline)))


def _repaired_result(ctx: AgentContext, assessment: Assessment, reserved_offer: ReservedOffer,
                     commitment: Commitment, action: RepairAction, now: datetime) -> StepAttempt:
    deviation = assessment.deviation
    finish = finish_under(ctx, reserved_offer, assessment.remaining_bytes, assessment.cap_gbps, now)
    return [RepairResult(commitment, reserved_offer.request, deviation.cause, deviation.links, "repaired", action,
                         finish)], None


def _try_modify(ctx: AgentContext, committed: Committed, placement: Placement,
                now: datetime) -> tuple[ReservedOffer, Commitment] | str:
    """modify_held on the commitment's current reserved offer; the reason as a string if the ledger or SENSE
    refused (everything is then as it was)."""
    reservation, reserved_offer = _reservation_and_offer_now(ctx, committed)
    try:
        return modify_held(ctx, reservation, reserved_offer, placement, now)
    except (InsufficientCapacity, SenseError) as error:
        return str(error)


def extend(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> StepAttempt:
    _, reserved_offer = _reservation_and_offer_now(ctx, assessment.committed)
    gbps = reserved_offer.placement.gbps

    # step1: the same placement at the same rate, its end moved later until the remaining bytes are expected through
    longer = _placement_through_by(ctx, reserved_offer, gbps, assessment.remaining_bytes, assessment.deadline,
                                   assessment.cap_gbps, now)
    if longer is None:
        return [], f"not through by {assessment.deadline:%H:%M:%S} at {gbps:g} Gbps"
    if longer.end <= reserved_offer.placement.end:
        return [], "the reservation already ends late enough"

    # step2: negotiate with scheudling agent
    proposal = candidate(ctx, "extend", assessment.commitment_id, "extend",
                         (Modification(assessment.committed, longer, assessment.cap_gbps),), now)
    if proposal is None:
        return [], "extension has no feasible unreserved capacity"
    approved, failure = approve(ctx, [proposal], now)
    if approved is None:
        return [], failure
    
    # step3: modify
    modified = _try_modify(ctx, assessment.committed, longer, now)
    if isinstance(modified, str):
        return [], modified
    return _repaired_result(ctx, assessment, *modified, "extend", now)


def network_can_help(ctx: AgentContext, assessment: Assessment, now: datetime) -> bool:
    """Conservative evidence gate, not a host-bottleneck diagnosis.
    """
    
    # `cap_gbps` only has a value in one case: when the cause of deviation is not located (unlocated), 
    # and the actual measured rate is lower than the reserved rate by more than the tolerance. 
    # For example, if 10 Gbps was reserved but only 3 Gbps was actually measured and the link is not 
    # reporting any faults, then cap_gbps = 3, otherwise it is None.
    if assessment.cap_gbps is not None:
        return False
    offer = assessment.committed.reserved_offer
    if not ctx.ledger.origin <= now < ctx.ledger.horizon_end:
        return False

    # Find out in which slot of the ledger `now` falls.
    slot = ctx.ledger.slots_covering(now, min(now + timedelta(microseconds=1), ctx.ledger.horizon_end))[0]
    
    # According to the ledger, what rate can the network theoretically provide for this flow in the current slot
    expected = expected_gbps(ctx.ledger, offer.placement.path, slot, offer.placement.gbps, offer.booking_id)
    
    seen = assessment.deviation.recent_gbps
    if seen is not None and seen < expected * (1 - ctx.cfg.progress_lag_tolerance):
        return False
    if assessment.deviation.cause in ("link_down", "congestion"):
        return True
    progress = assessment.deviation.progress

    # If the recent rate cannot be obtained (seen is empty), then use the average rate from the beginning
    # to the present as a fallback.
    if seen is None and progress.started_at is not None and now > progress.started_at:
        seen = progress.bytes_sent * 8 / 1e9 / (now - progress.started_at).total_seconds()
    return seen is not None and seen >= offer.placement.gbps * (1 - ctx.cfg.progress_lag_tolerance) # 5% in test case


def increase(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> StepAttempt:
    # step1: gate
    if not network_can_help(ctx, assessment, now):
        return [], "insufficient evidence that extra network capacity improves throughput"

    # step2: preparation
    reservation, reserved_offer = _reservation_and_offer_now(ctx, assessment.committed)
    deadline = min(assessment.deadline, reserved_offer.placement.end)
    rate_step = ctx.cfg.rate_step_gbps
    max_gbps = _path_capacity(ctx, reserved_offer.placement.path)
    higher_rates = [k * rate_step for k in range(int(reserved_offer.placement.gbps // rate_step) + 1,
                                                 int(max_gbps // rate_step) + 1)]
    failure = "no higher rate step gets through in time"

    # step3: Try rates one by one from low to high
    for gbps in higher_rates:
        faster = _placement_through_by(ctx, reserved_offer, gbps, assessment.remaining_bytes, deadline,
                                       assessment.cap_gbps, now)
        # Can it be completed on time?
        if faster is None:
            continue
        # Will the end time exceed the originally reserved time?
        if faster.end > reserved_offer.placement.end:
            continue
        # Do the ledger and SENSE agree?
        try:
            ctx.ledger.fork().replace(reserved_offer.booking_id, faster.rate_profile, now)
            new_offer, commitment = modify_held(ctx, reservation, reserved_offer, faster, now)
        except InsufficientCapacity as error: 
            failure = str(error)
            break
        except SenseError as error: # SENSE refusing ends the step
            return [], str(error)
        return _repaired_result(ctx, assessment, new_offer, commitment, "increase", now)
    return [], failure


def reroute(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> StepAttempt:
    # step1: check whether a reroute may be tried at all
    if not network_can_help(ctx, assessment, now):
        return [], "insufficient evidence that a path change improves throughput"
    if ctx.transfer_controller is None:
        return [], "no transfer controller connected to confirm the switch"
    last = ctx.last_reroute.get(assessment.commitment_id)
    if last is not None and (now - last).total_seconds() < ctx.cfg.reroute_cooldown_seconds:
        return [], "reroute cooldown has not elapsed"
    reservation, reserved_offer = _reservation_and_offer_now(ctx, assessment.committed)
    request = reserved_offer.request
    deadline = min(assessment.deadline, reserved_offer.placement.end)
    if now >= deadline:
        return [], "cannot preserve the promised completion time"   # time is up, no time to change

    # step2: list other paths that avoid damaged links, and refresh their observations
    damaged ={damage.link_id for damage in assessment.deviation.damage if damage.end > now}
    other_paths = [path for path in ctx.topology.paths(request.src, request.dst, ctx.cfg.max_paths)
                   if path != reserved_offer.placement.path and not damaged.intersection(path)]
    refresh(ctx, [(path, now, deadline) for path in other_paths], now)

    # step3: find placements on those paths that carry the remaining bytes in time, and take the earliest finish
    # a transfer not started yet keeps its start: the new circuit must not end before the transfer begins
    earliest = max(now, reserved_offer.placement.start)
    remaining_request = request.model_copy(update={
        "bytes": assessment.remaining_bytes,
        "window": TimeWindow(earliest_start=earliest, latest_finish=deadline)})
    candidates = []
    for path in other_paths:
        found = search(ctx.ledger, path, remaining_request, now, ctx.cfg.rate_step_gbps)
        if isinstance(found, list):                   # otherwise a reason why nothing fits
            for placement in found:
                finish = ctx.rate_model.finish_at_expected_rates(
                    [(placement.start, placement.end, placement.gbps)], assessment.remaining_bytes)
                if finish is not None and finish[1] <= min(deadline, placement.end):
                    candidates.append(placement)
    if not candidates:
        return [], "no other path has room in time"
    best = min(candidates, key=lambda placement: (placement.end, placement.start))   # earliest finish, no pause

    # step4: open the new circuit alongside the old one
    new_id =ctx.new_id(f"{reservation.reserve_id}/{reserved_offer.offer_id}/reroute")
    try:
        new_offer = open_circuit(ctx, reserved_offer, best, assessment.remaining_bytes,
                                 booking_id=new_id, alias=new_id, now=now)
    except (InsufficientCapacity, SenseError) as error:
        return [], str(error)

    # step5: move the transfer onto the new circuit; if not confirmed, drop the new circuit
    try:
        switched = ctx.transfer_controller.switch(reserved_offer.instance_id, new_offer.instance_id, now)
    except Exception as error:
        switched = False
        failure = f"transfer switch failed: {error}"
    else:
        failure = "transfer switch was not confirmed"
    if not switched:
        _discard_circuit(ctx, new_offer, now)
        return [], failure

    # step6: record the new circuit and release the old one
    # Only the execution acknowledgement permits breaking the old circuit.
    commitment = record_change(ctx, reservation, reserved_offer, new_offer)
    ctx.last_reroute[assessment.commitment_id] = now
    _discard_circuit(ctx, reserved_offer, now)
    return _repaired_result(ctx, assessment, new_offer, commitment, "reroute", now)


def _discard_circuit(ctx: AgentContext, offer: ReservedOffer, now: datetime) -> None:
    _, failed = cancel_instances(ctx.sense, [offer.instance_id], now)
    if failed:
        ctx.orphans[offer.instance_id] = offer.booking_id
    else:
        ctx.ledger.free(offer.booking_id)


def _lenders(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> list[Committed]:
    """Lower-priority commitments not in ``cannot_lend`` booked between now and the assessed commitment's
    deadline that share a hop with it, lowest priority first. Under congestion the hop must be a squeezed
    one (several of our circuits share what it gives); otherwise any hop of its path."""
    deviation = assessment.deviation
    shared = set(deviation.links) if deviation.cause == "congestion" else set(assessment.committed.reserved_offer.placement.path)
    lenders = [lender for lender in ctx.committed()
               if lender.reserved_offer.request.priority < assessment.priority
               and lender.commitment.commitment_id not in cannot_lend
               and shared & set(lender.reserved_offer.placement.path)
               and lender.reserved_offer.placement.end > now
               and lender.reserved_offer.placement.start < assessment.deadline]
    return sorted(lenders, key=lambda lender: lender.reserved_offer.request.priority)


def _remaining_bytes(ctx: AgentContext, reserved_offer: ReservedOffer, now: datetime) -> int:
    return reserved_offer.request.bytes - ctx.flows.progress(reserved_offer.instance_id, now).bytes_sent


def _lender_result(ctx: AgentContext, reserved_offer: ReservedOffer, commitment: Commitment, assessment: Assessment,
                   now: datetime) -> RepairResult:
    deviation = assessment.deviation
    finish = finish_under(ctx, reserved_offer, _remaining_bytes(ctx, reserved_offer, now), None, now)
    return RepairResult(commitment, reserved_offer.request, deviation.cause, deviation.links, "repaired", "lend",
                        finish, lent_to=assessment.commitment_id)


def borrow(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> StepAttempt:
    """Build complete allocations on a private ledger, ask the scheduler to choose, then execute."""
    if not network_can_help(ctx, assessment, now):
        return [], "insufficient evidence that network reallocation improves throughput"
    trial = replace(ctx, ledger=ctx.ledger.fork())
    loans: dict[str, Modification] = {}
    candidates = []
    target = assessment.committed.reserved_offer
    for lender in _lenders(ctx, assessment, now, cannot_lend):
        offer = lender.reserved_offer
        remaining = _remaining_bytes(ctx, offer, now)
        if remaining <= 0:
            continue
        deadline = min(offer.request.window.latest_finish, ctx.ledger.horizon_end,
                       ctx.repair_deadlines.get(lender.commitment.commitment_id, ctx.ledger.horizon_end))
        step = ctx.cfg.rate_step_gbps
        for k in range(math.ceil(offer.placement.gbps / step - EPS_GBPS) - 1, 0, -1):
            slower = _placement_through_by(trial, offer, k * step, remaining, deadline, None, now)
            if slower is None:
                break
            try:
                trial.ledger.replace(offer.booking_id, slower.rate_profile, now)
            except InsufficientCapacity:
                continue
            loans[lender.commitment.commitment_id] = Modification(lender, slower)
            rates = [target.placement.gbps] + [k * step for k in range(
                int(target.placement.gbps // step) + 1, int(_path_capacity(ctx, target.placement.path) // step) + 1)]
            for rate in rates:
                placement = _placement_through_by(trial, target, rate, assessment.remaining_bytes,
                                                   assessment.deadline, assessment.cap_gbps, now)
                if placement is None:
                    continue
                action = "extend" if rate == target.placement.gbps else "increase"
                plan = candidate(ctx, "borrow", assessment.commitment_id, action,
                                 (*loans.values(), Modification(assessment.committed, placement, assessment.cap_gbps)), now)
                if plan is not None:
                    candidates.append(plan)
                    break
    if not candidates:
        return [], "lending from lower-priority commitments cannot produce a feasible complete plan"
    approved, failure = approve(ctx, candidates, now)
    if approved is None:
        return [], failure
    changed = []
    for change in approved.modifications:
        modified = _try_modify(ctx, change.committed, change.placement, now)
        if isinstance(modified, str):
            retained = []
            for previous, offer_now, commitment in reversed(changed):
                restored = _try_modify(ctx, previous.committed, previous.committed.reserved_offer.placement, now)
                if isinstance(restored, str):
                    retained.append(_lender_result(ctx, offer_now, commitment, assessment, now))
            suffix = f"; rollback failed for {[r.commitment.commitment_id for r in retained]}" if retained else ""
            return retained, f"approved borrow execution failed: {modified}{suffix}"
        changed.append((change, *modified))
    _, target_now, target_commitment = changed[-1]
    results, _ = _repaired_result(ctx, assessment, target_now, target_commitment,
                                  approved.proposal.target_action, now)
    results += [_lender_result(ctx, offer_now, commitment, assessment, now)
                for _, offer_now, commitment in changed[:-1]]
    return results, None


REPAIR_STEPS = {"extend": extend, "increase": increase, "reroute": reroute, "borrow": borrow}


# ── report ────────────────────────────────────────────────────────────────

def to_report(result: RepairResult) -> DeviationReport:
    p50, p95 = result.finish or (None, None)
    commitment = result.commitment
    return DeviationReport(commitment_id=commitment.commitment_id, transfer_id=commitment.transfer_id,
                           workflow_id=commitment.workflow_id, cause=result.cause, links=list(result.links),
                           outcome=result.outcome, action=result.action, lent_to=result.lent_to,
                           predicted_finish_p50=p50, predicted_finish_p95=p95,
                           latest_finish=result.request.window.latest_finish, commitment=commitment)


def report(ctx: AgentContext, results: list[RepairResult], conditions: dict[str, RepairConditions],
           now: datetime) -> dict[Cause, list[DeviationReport]]:
    """Remember each failed attempt, but only send an unresolved report if its contents changed."""
    by_cause: dict[Cause, list[DeviationReport]] = {}
    for result in results:
        message = to_report(result)
        commitment_id = result.commitment.commitment_id
        if result.outcome == "unresolved":
            # Capture pre-repair inputs: another repair may have changed capacity during this run.
            ctx.failed_repairs[commitment_id] = FailedRepair(
                conditions[commitment_id], now + timedelta(seconds=ctx.cfg.repair_retry_seconds))
            if ctx.reported_unresolved.get(commitment_id) == message:
                continue
            ctx.reported_unresolved[commitment_id] = message
        else:
            ctx.forget_repair(commitment_id)
        by_cause.setdefault(result.cause, []).append(message)
    return by_cause
