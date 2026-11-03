"""Graph A · release branch (step 5b): give back a reservation, committed or not, in whole or in part.

    START → validate_release ─fail─► respond
              │ ok
              ▼
            sense_cancel → ledger_release → respond → END

A reserved item holds a pending booking (rolled back); a committed one holds a confirmed booking
(released) and a Commitment (dropped). Releasing only some offers serves e.g. a transfer that finished
early while the rest of the group keeps its circuits.

If SENSE fails to cancel an item, that item stays held: the network still carries it, so its booking
is kept and the error names it. The items that were cancelled are given back all the same, and the
release may be retried for the rest; an instance SENSE already reports as cancelled is not cancelled
again, so retrying is safe. The expiry sweep gives back expired reservations with the same pieces
(reclaim.py).
"""

from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from ..context import AgentContext, Reservation, ReservedOffer
from ..reclaim import cancel_items, give_back
from ..schemas import ErrorResponse, ReleaseAck, ReleaseRequest
from .common import on_error, parse_request


class ReleaseState(TypedDict, total=False):
    raw: dict                                     # input: the scheduling agent's ReleaseRequest as a dict
    now: datetime                                 # input: current time
    request: ReleaseRequest                       # written by validate_release
    reservation: Reservation                      # written by validate_release
    targets: list[ReservedOffer]                  # written by validate_release: the items to give back
    cancelled: list[str]                          # written by sense_cancel: offer_ids whose SENSE instance is cancelled
    error: ErrorResponse                          # written by whichever node fails
    response: ReleaseAck | ErrorResponse          # output


# ── nodes ────────────────────────────────────────────────────────────────

def validate_release(state: ReleaseState, runtime: Runtime[AgentContext]) -> dict:
    """Find the reservation and the items to give back (every item still held if none are named)."""
    ctx, req = runtime.context, parse_request(ReleaseRequest, state["raw"])
    if isinstance(req, ErrorResponse):
        return {"error": req}

    def fail(code: str, detail: str) -> dict:
        return {"request": req, "error": ErrorResponse(request_id=req.request_id, code=code, detail=detail)}

    r = ctx.reservations.get(req.reserve_id)
    if r is None:
        return fail("not_found", f"unknown reservation {req.reserve_id}")
    held = {i.offer_id: i for i in r.held}
    if req.offer_ids is None:
        if not held:
            return fail("conflict", f"{req.reserve_id} is already {r.state}")
        return {"request": req, "reservation": r, "targets": list(held.values())}
    unknown = [o for o in req.offer_ids if o not in {i.offer_id for i in r.items}]
    if unknown:
        return fail("not_found", f"offers not in {req.reserve_id}: {unknown}")
    gone = [o for o in req.offer_ids if o not in held]
    if gone:
        return fail("conflict", f"offers already released: {gone}")
    return {"request": req, "reservation": r, "targets": [held[o] for o in req.offer_ids]}


def sense_cancel(state: ReleaseState, runtime: Runtime[AgentContext]) -> dict:
    """Cancel each target's SENSE instance, going on past failures so that every item that can be given
    back is."""
    cancelled, failed = cancel_items(runtime.context.sense, state["targets"], state["now"])
    out: dict = {"cancelled": cancelled}
    if failed:
        stuck = [f"{o} ({e})" for o, e in failed.items()]
        out["error"] = ErrorResponse(request_id=state["request"].request_id, code="sense_failure",
                                     detail=f"cancel failed, still held: {stuck}; released: {out['cancelled']}; "
                                            "release may be retried")
    return out


def ledger_release(state: ReleaseState, runtime: Runtime[AgentContext]) -> dict:
    """Give back the bookings of the cancelled items and drop their commitments."""
    give_back(runtime.context, state["reservation"], state["cancelled"])
    return {}


def respond(state: ReleaseState) -> dict:
    if "error" in state:
        return {"response": state["error"]}
    return {"response": ReleaseAck(reserve_id=state["reservation"].reserve_id, offer_ids=state["cancelled"])}


# ── graph ────────────────────────────────────────────────────────────────

def build_release_graph():
    g = StateGraph(ReleaseState, context_schema=AgentContext)
    g.add_node("validate_release", validate_release)
    g.add_node("sense_cancel", sense_cancel)
    g.add_node("ledger_release", ledger_release)
    g.add_node("respond", respond)
    g.add_edge(START, "validate_release")
    g.add_conditional_edges("validate_release", on_error("sense_cancel"), ["sense_cancel", "respond"])
    g.add_edge("sense_cancel", "ledger_release")  # even after a failed cancel: give back what was cancelled
    g.add_edge("ledger_release", "respond")
    g.add_edge("respond", END)
    return g.compile()
