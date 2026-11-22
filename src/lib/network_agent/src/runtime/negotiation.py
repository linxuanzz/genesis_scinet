"""Pure allocation proposals and scheduler decisions, separate from network execution."""

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Literal

from ..adapters.telemetry import refresh_stale
from ..context.context import AgentContext, Committed
from ..models.schemas import RepairChange, RepairDecision, RepairProposal
from ..planning.placement import Placement
from ..state.ledger import InsufficientCapacity
from .forecast import finish_under


@dataclass(frozen=True)
class Modification:
    committed: Committed
    placement: Placement
    cap_gbps: float | None = None


@dataclass(frozen=True)
class Candidate:
    proposal: RepairProposal
    modifications: tuple[Modification, ...]  # lenders first, target last


def check_modifications(ctx: AgentContext, modifications: tuple[Modification, ...], now: datetime) -> list[RepairChange]:
    """Check the complete allocation on a private ledger, then forecast every affected transfer."""
    trial = replace(ctx, ledger=ctx.ledger.fork())
    for change in modifications:
        trial.ledger.replace(change.committed.reserved_offer.booking_id, change.placement.rate_profile, now)
    details = []
    for change in modifications:
        committed, placement = change.committed, change.placement
        old = committed.reserved_offer
        remaining = old.request.bytes - ctx.flows.progress(old.instance_id, now).bytes_sent
        if remaining <= 0:
            raise ValueError("transfer already finished")
        before = finish_under(ctx, old, remaining, change.cap_gbps, now)
        after = finish_under(trial, replace(old, placement=placement), remaining, change.cap_gbps, now)
        deadline = min(old.request.window.latest_finish, ctx.ledger.horizon_end,
                       ctx.repair_deadlines.get(committed.commitment.commitment_id, ctx.ledger.horizon_end))
        if after is None or after[1] > min(deadline, placement.end):
            raise ValueError("proposed allocation cannot finish in time")
        details.append(RepairChange(commitment_before=committed.commitment, path=list(placement.path),
                                     rate_profile_after=placement.rate_profile,
                                     predicted_finish_before=before[1] if before else None,
                                     predicted_finish_after=after[1], latest_finish=deadline))
    return details


def candidate(ctx: AgentContext, kind: Literal["extend", "borrow"], target_id: str,
              action: Literal["extend", "raise_rate"], modifications: tuple[Modification, ...],
              now: datetime) -> Candidate | None:
    try:
        details = check_modifications(ctx, modifications, now)
    except (InsufficientCapacity, ValueError):
        return None
    proposal = RepairProposal(proposal_id=ctx.new_id("repair"), kind=kind, target_commitment_id=target_id,
                               target_action=action, effective_at=now, changes=details)
    return Candidate(proposal, modifications)


def approve(ctx: AgentContext, candidates: list[Candidate], now: datetime) -> tuple[Candidate | None, str | None]:
    """Approval grants only the selected allocation; observations and commitments are rechecked afterwards."""

    # step1: ask the scheduling agent which proposal to take
    proposals = [plan.proposal for plan in candidates]
    ctx.repair_proposals.extend(proposals)
    if ctx.repair_coordinator is None:
        return None, "scheduler approval required; no coordinator connected"
    try:
        response = ctx.repair_coordinator.choose(proposals, now)
        decision = RepairDecision() if response is None else RepairDecision.model_validate(response)
    except Exception as error:
        return None, f"scheduler decision failed: {error}"
    target = proposals[0].target_commitment_id
    if decision.latest_finish is not None:
        ctx.repair_deadlines[target] = min(decision.latest_finish,
                                           ctx.repair_deadlines.get(target, decision.latest_finish))
        ctx.repair_constraint_commitments[target] = ctx.commitments[target]
    if decision.proposal_id is None:
        return None, f"scheduler rejected: {decision.reason or 'no acceptable plan'}"

    chosen = next((plan for plan in candidates if plan.proposal.proposal_id == decision.proposal_id), None)
    if chosen is None:
        return None, "scheduler selected an unknown proposal"

    # step2: check whether "our own records" have changed waiting for the reply
    current ={c.commitment.commitment_id: c for c in ctx.committed()}
    if any(current.get(change.committed.commitment.commitment_id) != change.committed
           for change in chosen.modifications):
        return None, "commitment changed while awaiting approval"
    if any(change.committed.commitment.commitment_id in ctx.reported_unresolved
           for change in chosen.modifications if change.committed.commitment.commitment_id != target):
        return None, "a proposed lender now has an unresolved deviation"

    # step3: check whether "the internet" can still handle the load
    spans =[(change.placement.path, now, change.placement.end) for change in chosen.modifications]
    refresh_stale(ctx.ledger, ctx.telemetry, spans, now, force={link for path, _, _ in spans for link in path})
    try:
        checked = check_modifications(ctx, chosen.modifications, now)
    except (InsufficientCapacity, ValueError) as error:
        return None, f"approved plan is no longer feasible: {error}"
    # A later forecast could break a downstream plan that the scheduler just approved.
    if any(new.predicted_finish_after > old.predicted_finish_after
           for old, new in zip(chosen.proposal.changes, checked)):
        return None, "approved completion estimate is no longer achievable"
    return chosen, None
