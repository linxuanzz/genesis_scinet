"""State-changing operations on what we hold, shared by graph A's branches and graph B's repairs (step 7).

Graph A's nodes each call one piece, so that its branches keep their shape; graph B chains them, with
the same rollback, through the two composites at the end:

    modify (same circuit)  change_booking → change_circuit (→ restore_booking if SENSE refuses) → record_change
    new circuit            ledger.pending → compile_intent → propagate_intents → commit_instance → ledger.confirm,
                           undo_holds if SENSE refuses

Giving back (cancel + release) is in reclaim.py and sense.cancel_instances.
"""

from dataclasses import replace
from datetime import datetime

from ..adapters.sense import SenseAdapter, SenseError, cancel_instances
from ..context.context import AgentContext, Reservation, ReservedOffer
from ..models.schemas import Commitment, EndpointBinding, ServiceIntent, ServiceState
from ..planning.circuit import compile_intent
from ..planning.placement import Placement


# ── modify: same path, circuit and VLAN ───────────────────────────────────

def change_booking(ctx: AgentContext, reserved_offer: ReservedOffer, p: Placement, now: datetime) -> None:
    """Give the reserved offer's booking the placement's profile; raises InsufficientCapacity and changes nothing if
    what it adds does not fit (see CapacityLedger.replace)."""
    ctx.ledger.replace(reserved_offer.booking_id, p.rate_profile, now)


def change_circuit(ctx: AgentContext, reserved_offer: ReservedOffer, p: Placement, now: datetime) -> ServiceIntent:
    """Ask SENSE to change the reserved offer's instance in place, under the same alias; raises SenseError."""
    req = reserved_offer.request
    intent = compile_intent(p, req.src, req.dst, alias=reserved_offer.intent.alias)
    ctx.sense.modify(reserved_offer.instance_id, intent, now)
    return intent


def restore_booking(ctx: AgentContext, reserved_offer: ReservedOffer, now: datetime) -> None:
    """Put the reserved offer's old profile back after SENSE refused a change. It fits: nothing else changed
    in between."""
    ctx.ledger.replace(reserved_offer.booking_id, reserved_offer.placement.rate_profile, now)


def record_change(ctx: AgentContext, r: Reservation, old: ReservedOffer, new: ReservedOffer) -> Commitment | None:
    """Put the changed reserved offer into the reservation and, if it was committed, update its commitment (profile,
    and circuit and binding if the circuit changed). Returns the updated commitment."""
    r.reserved_offers[r.reserved_offers.index(old)] = new
    cid = r.commitment_ids.get(new.offer_id)
    if cid is None:
        return None
    c = ctx.commitments[cid]
    update: dict = {"rate_profile": new.placement.rate_profile}
    if new.instance_id != old.instance_id:
        update |= {"circuit_id": new.instance_id,
                   "binding": c.binding.model_copy(update={"vlan": new.vlan})}
    ctx.commitments[cid] = c.model_copy(update=update)
    return ctx.commitments[cid]


def modify_held(ctx: AgentContext, r: Reservation, reserved_offer: ReservedOffer, p: Placement,
                now: datetime) -> tuple[ReservedOffer, Commitment | None]:
    """change_booking + change_circuit + record_change; if SENSE refuses, the old profile is put back.
    Raises InsufficientCapacity or SenseError, with nothing changed."""
    change_booking(ctx, reserved_offer, p, now)
    try:
        intent = change_circuit(ctx, reserved_offer, p, now)
    except SenseError:
        restore_booking(ctx, reserved_offer, now)
        raise
    new = replace(reserved_offer, placement=p, intent=intent)
    return new, record_change(ctx, r, reserved_offer, new)


# ── new circuit: hold, propagate, commit ──────────────────────────────────

def propagate_intents(sense: SenseAdapter, intents: dict[str, ServiceIntent],
                      now: datetime) -> tuple[dict[str, ServiceState], tuple[str, SenseError] | None]:
    """Propagate each intent in order, stopping at the first failure. Returns the instances created (by
    key) and the failure, if any, so that the caller can undo them."""
    instances: dict[str, ServiceState] = {}
    for key, intent in intents.items():
        try:
            instances[key] = sense.propagate(intent, now)
        except SenseError as e:
            return instances, (key, e)
    return instances, None


def undo_holds(ctx: AgentContext, bookings: dict[str, str], instances: dict[str, ServiceState],
               now: datetime) -> dict[str, SenseError]:
    """Undo a hold that was not committed: cancel the instances created, roll back the pending bookings.
    An instance that fails to cancel becomes an orphan, keeping its booking until the expiry sweep cancels
    it. Returns {instance_id: error} for those."""
    _, failed = cancel_instances(ctx.sense, [s.instance_id for s in instances.values()], now)
    for key, booking_id in bookings.items():
        if key in instances and instances[key].instance_id in failed:
            ctx.orphans[instances[key].instance_id] = booking_id
        else:
            ctx.ledger.rollback(booking_id)
    return failed


def commit_instance(sense: SenseAdapter, instance_id: str, now: datetime) -> ServiceState:
    """Commit one instance, unless SENSE already reports it committed (a retried commit). Raises SenseError."""
    s = sense.state(instance_id)
    return s if s.state == "committed" else sense.commit(instance_id, now)


def make_commitment(ctx: AgentContext, reserved_offer: ReservedOffer, s: ServiceState) -> Commitment:
    """The Commitment of a committed reserved offer, with its endpoint binding."""
    req = reserved_offer.request
    src, dst = reserved_offer.intent.terminals
    return Commitment(commitment_id=ctx.new_id("cmt"), transfer_id=req.id, workflow_id=req.workflow_id,
                      circuit_id=s.instance_id, rate_profile=reserved_offer.placement.rate_profile,
                      binding=EndpointBinding(transfer_id=req.id, src_uri=src.uri, dst_uri=dst.uri, vlan=s.vlan))


def open_circuit(ctx: AgentContext, old: ReservedOffer, p: Placement, nbytes: int, booking_id: str, alias: str,
                 now: datetime) -> ReservedOffer:
    """A new, committed circuit for ``old``'s transfer (its remaining nbytes) along the placement: hold in
    the ledger, propagate, commit, confirm. Raises InsufficientCapacity or SenseError with everything
    undone (an instance that fails to cancel is left as an orphan for the sweep). The old circuit is
    untouched: closing it is the caller's step (make-before-break)."""
    ctx.ledger.pending(booking_id, p.path, p.rate_profile)
    req = old.request.model_copy(update={"bytes": nbytes})
    intent = compile_intent(p, req.src, req.dst, alias=alias)
    instances, failure = propagate_intents(ctx.sense, {"new": intent}, now)
    if failure is not None:
        undo_holds(ctx, {"new": booking_id}, instances, now)
        raise failure[1]
    try:
        s = commit_instance(ctx.sense, instances["new"].instance_id, now)
    except SenseError:
        undo_holds(ctx, {"new": booking_id}, instances, now)
        raise
    ctx.ledger.confirm(booking_id)
    return ReservedOffer(offer_id=old.offer_id, request=req, placement=p, booking_id=booking_id, intent=intent,
                         instance_id=s.instance_id, vlan=s.vlan)
