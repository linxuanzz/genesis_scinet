"""Graph A · commit branch (step 5a): confirm a reservation, turning each reserved offer into a commitment.

    START → validate_commit ─fail─► respond
              │ ok
              ▼
            sense_commit ─fail─► respond                (ledger untouched; the reservation stays, commit can be retried)
              │ ok
              ▼
            ledger_confirm → respond → END

Nothing is debited here: capacity was already taken at reserve, so commit only asks SENSE to push the
configuration and then marks the ledger bookings confirmed. A failed commit therefore rolls nothing
back: SENSE still holds the reserved instances and the scheduling agent may retry before the TTL.

A commit may fail halfway through a group (some instances committed, the rest not). A retry skips the
instances SENSE already reports as committed, so retrying is safe.
"""

from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from ..context import AgentContext, Reservation
from ..schemas import CommitAck, Commitment, CommitRequest, EndpointBinding, ErrorResponse, ServiceState
from ..sense import SenseError
from .common import on_error


class CommitState(TypedDict, total=False):
    raw: dict                                     # input: the scheduling agent's CommitRequest as a dict
    now: datetime                                 # input: current time
    request: CommitRequest                        # written by validate_commit
    reservation: Reservation                      # written by validate_commit
    committed: dict[str, ServiceState]            # written by sense_commit: offer_id → committed SENSE instance
    commitments: list[Commitment]                 # written by ledger_confirm
    error: ErrorResponse                          # written by whichever node fails
    response: CommitAck | ErrorResponse           # output


# ── nodes ────────────────────────────────────────────────────────────────

def validate_commit(state: CommitState, runtime: Runtime[AgentContext]) -> dict:
    """Find the reservation and check it can still be committed. Nothing is written."""
    ctx, raw = runtime.context, state["raw"]
    try:
        req = CommitRequest.model_validate(raw)
    except ValidationError as e:
        request_id = raw.get("request_id") if isinstance(raw, dict) else None
        return {"error": ErrorResponse(request_id=str(request_id or "unknown"), code="invalid_request",
                                       detail="; ".join(err["msg"] for err in e.errors()))}

    def fail(code: str, detail: str) -> dict:
        return {"request": req, "error": ErrorResponse(request_id=req.request_id, code=code, detail=detail)}

    r = ctx.reservations.get(req.reserve_id)
    if r is None:
        return fail("not_found", f"unknown reservation {req.reserve_id}")
    if r.state == "committed":
        return fail("conflict", f"{req.reserve_id} is already committed")
    if state["now"] >= r.expires_at:
        return fail("expired", f"{req.reserve_id} expired at {r.expires_at:%H:%M:%S}")
    return {"request": req, "reservation": r}


def sense_commit(state: CommitState, runtime: Runtime[AgentContext]) -> dict:
    """Ask SENSE to commit every instance of the reservation, skipping those already committed by an
    earlier attempt. Stops at the first failure."""
    sense, now = runtime.context.sense, state["now"]
    committed: dict[str, ServiceState] = {}
    for item in state["reservation"].items:
        try:
            s = sense.state(item.instance_id)
            committed[item.offer_id] = s if s.state == "committed" else sense.commit(item.instance_id, now)
        except SenseError as e:
            return {"error": ErrorResponse(request_id=state["request"].request_id, code="sense_failure",
                                           detail=f"{item.offer_id}: {e}; reservation kept, commit may be retried")}
    return {"committed": committed}


def ledger_confirm(state: CommitState, runtime: Runtime[AgentContext]) -> dict:
    """Confirm the bookings and turn each reserved offer into a Commitment with its endpoint binding."""
    ctx, r = runtime.context, state["reservation"]
    commitments = []
    for item in r.items:
        ctx.ledger.confirm(item.booking_id)
        req = ctx.offer_book[item.offer_id].request
        s = state["committed"][item.offer_id]
        src, dst = item.intent.terminals
        c = Commitment(commitment_id=ctx.new_id("cmt"), transfer_id=req.id, workflow_id=req.workflow_id,
                       circuit_id=s.instance_id, rate_profile=item.placement.rate_profile,
                       binding=EndpointBinding(transfer_id=req.id, src_uri=src.uri, dst_uri=dst.uri, vlan=s.vlan))
        ctx.commitments[c.commitment_id] = c
        commitments.append(c)
    r.state = "committed"
    return {"commitments": commitments}


def respond(state: CommitState) -> dict:
    if "error" in state:
        return {"response": state["error"]}
    return {"response": CommitAck(reserve_id=state["reservation"].reserve_id, commitments=state["commitments"])}


# ── graph ────────────────────────────────────────────────────────────────

def build_commit_graph():
    g = StateGraph(CommitState, context_schema=AgentContext)
    g.add_node("validate_commit", validate_commit)
    g.add_node("sense_commit", sense_commit)
    g.add_node("ledger_confirm", ledger_confirm)
    g.add_node("respond", respond)
    g.add_edge(START, "validate_commit")
    g.add_conditional_edges("validate_commit", on_error("sense_commit"), ["sense_commit", "respond"])
    g.add_conditional_edges("sense_commit", on_error("ledger_confirm"), ["ledger_confirm", "respond"])
    g.add_edge("ledger_confirm", "respond")
    g.add_edge("respond", END)
    return g.compile()
