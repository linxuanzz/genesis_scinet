"""Graph B's judgement and local repairs (step 7): triage, plan_local_repair, execute_repair, report_deviation.

The two judgements (the ◇ nodes of graph B) sit behind ``RuntimePolicy``; ``RulePolicy`` is the first,
rule-based version, and build_runtime_graph takes another in its place.

    triage   finishes_in_reservation (p95 of the remaining bytes is within the reservation's end) → nothing to do;
             same failed repair conditions and retry not yet due → defer; otherwise → repair
    plan_local_repair
             which repairs are worth trying, in order (smallest change first):

        extend      same circuit and rate, a later end
        raise_rate  same circuit, the lowest higher rate step that gets through by the deadline (the end
                    never moves earlier)
        reroute     a new circuit on another candidate path, make-before-break: the earliest-finishing
                    placement for the remaining bytes (placement.search) is held, propagated and committed
                    before the old circuit is cancelled and its booking given back; the commitment keeps
                    its id and gets the new circuit and VLAN, and the WMS moves the rest of the transfer
        borrow      slow down lower-priority commitments that share a hop (lowest priority first), one rate
                    step at a time and only as long as each still gets through by its own latest_finish,
                    retrying extend and raise_rate after every step, so that the least slack is taken;
                    the lenders are put back if that does not help

             An off-path cause (unlocated, still slow) gets extend only: more rate or another path does not
             lift a limit outside the network. A late start gets no borrowing: others do not pay for it.
             Nothing is worth trying if the remaining bytes cannot get through by the deadline even at the
             full capacity of the best candidate path.

Every repair asks for a reservation that gets the remaining bytes through by the deadline (latest_finish,
at most the ledger's horizon), by the forecast of forecast.py. A step whose ledger or SENSE call fails
leaves everything as it was, and the next step is tried; when none works the outcome is unresolved and
the commitment's resources are left as they are. Higher priority is repaired first, so it gets the
capacity first; commitments being repaired in the same run, or waiting for the scheduling agent, do not
lend. The state-changing steps are those of graph A (operations.py).
"""

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal, Protocol

from ..adapters.sense import SenseError, cancel_instances
from ..adapters.telemetry import refresh_stale
from ..context.context import AgentContext, Committed, FailedRepair, RepairConditions, Reservation, ReservedOffer
from ..models.schemas import Cause, Commitment, DeviationReport, RepairAction, TimeWindow, TransferRequest
from ..planning.placement import Placement, bytes_at, search
from ..shared.operations import modify_held, open_circuit, record_change
from ..state.ledger import EPS_GBPS, InsufficientCapacity
from .forecast import Assessment, expected_rates_on_circuit, finish_under

TriageVerdict = Literal["finishes_in_reservation", "retry_deferred", "repair"]
NOTHING_TO_TRY = "no repair can get the remaining bytes through by the deadline"
Step = Literal["extend", "raise_rate", "reroute", "borrow"]


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
        candidate_paths = ctx.topology.paths(request.src, request.dst, ctx.cfg.max_paths)
        best_gbps = max(_path_capacity(ctx, path) for path in candidate_paths)
        if assessment.cap_gbps is not None:
            best_gbps = min(best_gbps, assessment.cap_gbps)
        seconds_left = (assessment.deadline - now).total_seconds()
        if seconds_left <= 0 or bytes_at(best_gbps, seconds_left) < assessment.remaining_bytes:
            return []
        if assessment.cap_gbps is not None:
            return ["extend"]
        steps: list[Step] = ["extend"]
        current_path = reserved_offer.placement.path
        if reserved_offer.placement.gbps + ctx.cfg.rate_step_gbps <= _path_capacity(ctx, current_path) + EPS_GBPS:
            steps.append("raise_rate")
        if any(path != current_path for path in candidate_paths):
            steps.append("reroute")
        if (assessment.deviation.cause in ("link_down", "congestion")
                and _lenders(ctx, assessment, now, cannot_lend=set(ctx.reported_unresolved))):
            steps.append("borrow")
        return steps


# ── triage and plan_local_repair ──────────────────────────────────────────

def forget_changed_commitments(ctx: AgentContext) -> None:
    """Run even when detection finds no deviations, so releases and modifications clear old failures."""
    for commitment_id, failed in list(ctx.failed_repairs.items()):
        if ctx.commitments.get(commitment_id) != failed.conditions.commitment:
            ctx.forget_repair(commitment_id)


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
    refreshed = refresh_stale(ctx.ledger, ctx.telemetry, spans, now)
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
    return RepairConditions(assessment.deviation.cause, assessment.deviation.links, assessment.committed.commitment, request,
                            assessment.remaining_bytes, assessment.cap_gbps, paths, capacity, lender_state), refreshed


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
        tried: list[str] = []
        for step in plan.steps:
            step_results, failure = REPAIR_STEPS[step](ctx, plan.assessment, now, cannot_lend)
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
    """If this already booked offer is changed to a given rate, at what time should 
    the reserve be opened to transfer the remaining bytes? It returns the modified 
    new placement; If the data cannot be uploaded by the deadline, return None."""
    placement = reserved_offer.placement
    spans = expected_rates_on_circuit(ctx.ledger, placement.path, gbps, max(now, placement.start), deadline,
                                      reserved_offer.booking_id, cap)
    finish = ctx.rate_model.finish_at_expected_rates(spans, nbytes)
    if finish is None:
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
    # the same placement at the same rate, its end moved later until the remaining bytes are expected through
    longer = _placement_through_by(ctx, reserved_offer, gbps, assessment.remaining_bytes, assessment.deadline,
                                   assessment.cap_gbps, now)
    if longer is None:
        return [], f"not through by {assessment.deadline:%H:%M:%S} at {gbps:g} Gbps"
    if longer.end <= reserved_offer.placement.end:
        return [], "the reservation already ends late enough"
    modified = _try_modify(ctx, assessment.committed, longer, now)
    if isinstance(modified, str):
        return [], modified
    return _repaired_result(ctx, assessment, *modified, "extend", now)


def raise_rate(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> StepAttempt:
    reservation, reserved_offer = _reservation_and_offer_now(ctx, assessment.committed)
    rate_step = ctx.cfg.rate_step_gbps
    max_gbps = _path_capacity(ctx, reserved_offer.placement.path)
    higher_rates = [k * rate_step for k in range(int(reserved_offer.placement.gbps // rate_step) + 1,
                                                 int(max_gbps // rate_step) + 1)]
    failure = "no higher rate step gets through in time"
    for gbps in higher_rates:
        faster = _placement_through_by(ctx, reserved_offer, gbps, assessment.remaining_bytes, assessment.deadline,
                                       assessment.cap_gbps, now)
        if faster is None:
            continue
        try:
            new_offer, commitment = modify_held(ctx, reservation, reserved_offer, faster, now)
        except InsufficientCapacity as error:     # a higher rate asks for more, but may still fit where this
            failure = str(error)                  # one was refused for its later end: go on
            continue
        except SenseError as error:               # SENSE refusing ends the step
            return [], str(error)
        return _repaired_result(ctx, assessment, new_offer, commitment, "raise_rate", now)
    return [], failure


def reroute(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> StepAttempt:
    reservation, reserved_offer = _reservation_and_offer_now(ctx, assessment.committed)
    request = reserved_offer.request
    other_paths = [path for path in ctx.topology.paths(request.src, request.dst, ctx.cfg.max_paths)
                   if path != reserved_offer.placement.path]
    refresh_stale(ctx.ledger, ctx.telemetry, [(path, now, assessment.deadline) for path in other_paths], now)
    remaining_request = request.model_copy(update={
        "bytes": assessment.remaining_bytes,
        "window": TimeWindow(earliest_start=now, latest_finish=assessment.deadline)})
    candidates = []
    for path in other_paths:
        found = search(ctx.ledger, path, remaining_request, now, ctx.cfg.rate_step_gbps)
        if isinstance(found, list):                   # otherwise a reason why nothing fits
            candidates += found
    if not candidates:
        return [], "no other path has room in time"
    best = min(candidates, key=lambda placement: (placement.end, placement.start))   # earliest finish, no pause
    new_id = ctx.new_id(f"{reservation.reserve_id}/{reserved_offer.offer_id}/reroute")
    try:
        new_offer = open_circuit(ctx, reserved_offer, best, assessment.remaining_bytes,
                                 booking_id=new_id, alias=new_id, now=now)
    except (InsufficientCapacity, SenseError) as error:
        return [], str(error)
    _, failed = cancel_instances(ctx.sense, [reserved_offer.instance_id], now)
    if failed:
        # the expiry sweep cancels it and gives the booking back
        ctx.orphans[reserved_offer.instance_id] = reserved_offer.booking_id
    else:
        ctx.ledger.free(reserved_offer.booking_id)
    commitment = record_change(ctx, reservation, reserved_offer, new_offer)
    return _repaired_result(ctx, assessment, new_offer, commitment, "reroute", now)


def _lenders(ctx: AgentContext, assessment: Assessment, now: datetime, cannot_lend: set[str]) -> list[Committed]:
    """Lower-priority commitments not in ``cannot_lend`` that share a hop with the assessed commitment's path
    and are booked between now and its deadline, lowest priority first."""
    our_links = set(assessment.committed.reserved_offer.placement.path)
    lenders = [lender for lender in ctx.committed()
               if lender.reserved_offer.request.priority < assessment.priority
               and lender.commitment.commitment_id not in cannot_lend
               and our_links & set(lender.reserved_offer.placement.path)
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
    """Lower each lender one rate step at a time, as long as it still gets through by its own deadline,
    retrying extend and raise_rate after every step: the least slack is borrowed that does the job."""
    # commitment id → (lender, its reserved offer before lending, its reserved offer now, its commitment now)
    loans: dict[str, tuple[Committed, ReservedOffer, ReservedOffer, Commitment]] = {}

    def lender_results() -> list[RepairResult]:
        return [_lender_result(ctx, offer_now, commitment, assessment, now)
                for _, _, offer_now, commitment in loans.values()]

    rate_step = ctx.cfg.rate_step_gbps
    for lender in _lenders(ctx, assessment, now, cannot_lend):
        _, offer_before = _reservation_and_offer_now(ctx, lender)
        lender_remaining = _remaining_bytes(ctx, offer_before, now)
        if lender_remaining <= 0:
            continue
        lender_deadline = min(offer_before.request.window.latest_finish, ctx.ledger.horizon_end)
        steps_now = math.ceil(offer_before.placement.gbps / rate_step - EPS_GBPS)
        lower_rates = [k * rate_step for k in range(steps_now - 1, 0, -1)]          # one step down at a time
        for gbps in lower_rates:
            _, offer_now = _reservation_and_offer_now(ctx, lender)
            slower = _placement_through_by(ctx, offer_now, gbps, lender_remaining, lender_deadline, None, now)
            if slower is None:
                break                                 # lower still would be later still
            modified = _try_modify(ctx, lender, slower, now)
            if isinstance(modified, str):
                break
            loans[lender.commitment.commitment_id] = (lender, offer_before, *modified)
            for retry in (extend, raise_rate):
                retry_results, failure = retry(ctx, assessment, now, cannot_lend)
                if failure is None:
                    return retry_results + lender_results(), None
    if not loans:
        return [], "no lower-priority commitment can lend"
    not_restored = []
    for commitment_id, (lender, offer_before, *_) in reversed(list(loans.items())):   # did not help: put back
        if isinstance(_try_modify(ctx, lender, offer_before.placement, now), str):
            not_restored.append(commitment_id)
        else:
            del loans[commitment_id]
    if not_restored:
        return lender_results(), f"lending did not help; could not put back {not_restored}"
    return lender_results(), "lending from lower-priority commitments did not help"


REPAIR_STEPS = {"extend": extend, "raise_rate": raise_rate, "reroute": reroute, "borrow": borrow}


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
