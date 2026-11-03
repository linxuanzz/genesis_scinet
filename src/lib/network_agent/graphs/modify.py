"""Graph A · modify branch (step 5b): change the rate and/or time range of one reserved or committed offer.

    START → validate_modify ─fail─► respond
              │ ok
              ▼
            recheck_capacity → ledger_replace ─fail─► respond
                                 │ ok
                                 ▼
                               sense_modify ─ok──► record_modify → respond → END
                                            └fail─► ledger_restore → respond

The offer keeps its path, circuit (SENSE instance) and VLAN; only the profile changes. Moving to another
path is not a modify: the scheduling agent reserves the new placement and then releases the old one.

The ledger is changed first, atomically, with the old booking not counted against the new profile (so
a transfer can grow into the capacity it already holds). If SENSE then refuses, the old profile is put
back. Each circuit carries one constant rate (see circuit.py), so the new profile is a single segment.
Once the old profile has started, its start cannot move: only the rate and the end can change.
"""

from dataclasses import replace
from datetime import datetime
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from ..circuit import compile_intent
from ..context import AgentContext, Reservation, ReservedOffer
from ..ledger import InsufficientCapacity
from ..placement import Placement
from ..schemas import ErrorResponse, ModifyAck, ModifyRequest, ServiceIntent
from ..sense import SenseError
from ..telemetry import refresh_stale
from .common import on_error, parse_request


class ModifyState(TypedDict, total=False):
    raw: dict                                     # input: the scheduling agent's ModifyRequest as a dict
    now: datetime                                 # input: current time
    request: ModifyRequest                        # written by validate_modify
    reservation: Reservation                      # written by validate_modify
    item: ReservedOffer                           # written by validate_modify: the offer as it is now
    placement: Placement                          # written by validate_modify: the offer with its new profile
    refreshed: list[str]                          # written by recheck_capacity: links refreshed this time
    intent: ServiceIntent                         # written by sense_modify: what SENSE now holds
    error: ErrorResponse                          # written by whichever node fails
    response: ModifyAck | ErrorResponse           # output


# ── nodes ────────────────────────────────────────────────────────────────

def validate_modify(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    """Find the offer and check the new profile against it. Nothing is written."""
    ctx, now, req = runtime.context, state["now"], parse_request(ModifyRequest, state["raw"])
    if isinstance(req, ErrorResponse):
        return {"error": req}

    def fail(code: str, detail: str) -> dict:
        return {"request": req, "error": ErrorResponse(request_id=req.request_id, code=code, detail=detail)}

    r = ctx.reservations.get(req.reserve_id)
    if r is None:
        return fail("not_found", f"unknown reservation {req.reserve_id}")
    if r.is_expired(now):
        return fail("expired", f"{req.reserve_id} expired at {r.expires_at:%H:%M:%S}")
    item = next((i for i in r.items if i.offer_id == req.offer_id), None)
    if item is None:
        return fail("not_found", f"offer {req.offer_id} is not in {req.reserve_id}")
    if item not in r.held:
        return fail("conflict", f"offer {req.offer_id} is already released")

    if len(req.rate_profile) != 1:
        return fail("invalid_request", "a circuit carries one constant rate: give a single segment")
    seg, old = req.rate_profile[0], item.placement
    if seg.end <= now:
        return fail("invalid_request", f"the new profile ends at {seg.end:%H:%M:%S}, already past")
    if old.start <= now and seg.start != old.start:
        return fail("invalid_request", f"{req.offer_id} started at {old.start:%H:%M:%S}; its start cannot move")
    if old.start > now and seg.start < now:
        return fail("invalid_request", f"the new profile starts at {seg.start:%H:%M:%S}, already past")
    if seg.end > ctx.ledger.horizon_end:
        return fail("invalid_request", f"the new profile ends after the ledger horizon {ctx.ledger.horizon_end}")
    return {"request": req, "reservation": r, "item": item,
            "placement": replace(old, start=seg.start, end=seg.end, gbps=seg.gbps)}


def recheck_capacity(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    """Refresh stale observations over the new time range, so that ledger_replace checks current numbers."""
    ctx, p = runtime.context, state["placement"]
    return {"refreshed": refresh_stale(ctx.ledger, ctx.telemetry, [(p.path, p.start, p.end)], state["now"])}


def ledger_replace(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    """Swap the booking's profile; if the new one does not fit, nothing changes."""
    try:
        runtime.context.ledger.replace(state["item"].booking_id, state["placement"].rate_profile)
    except InsufficientCapacity as e:
        return {"error": ErrorResponse(request_id=state["request"].request_id, code="conflict",
                                       detail=f"capacity not available: {e}")}
    return {}


def sense_modify(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    """Ask SENSE to change the instance in place, under the same alias."""
    item, req = state["item"], state["request"]
    intent = compile_intent(state["placement"], item.request.src, item.request.dst, alias=item.intent.alias)
    try:
        runtime.context.sense.modify(item.instance_id, intent, state["now"])
    except SenseError as e:
        return {"error": ErrorResponse(request_id=req.request_id, code="sense_failure",
                                       detail=f"{req.offer_id}: {e}; the old profile stays")}
    return {"intent": intent}


def ledger_restore(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    """SENSE refused: put the old profile back. It fits, since nothing else changed in between."""
    runtime.context.ledger.replace(state["item"].booking_id, state["item"].placement.rate_profile)
    return {}


def record_modify(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    """Write the new profile into the reservation and, if the offer was committed, into its commitment."""
    ctx, r, item = runtime.context, state["reservation"], state["item"]
    r.items[r.items.index(item)] = replace(item, placement=state["placement"], intent=state["intent"])
    cid = r.commitment_ids.get(item.offer_id)
    if cid is not None:
        ctx.commitments[cid] = ctx.commitments[cid].model_copy(
            update={"rate_profile": state["placement"].rate_profile})
    return {}


def respond(state: ModifyState, runtime: Runtime[AgentContext]) -> dict:
    if "error" in state:
        return {"response": state["error"]}
    r, offer_id = state["reservation"], state["item"].offer_id
    cid = r.commitment_ids.get(offer_id)
    return {"response": ModifyAck(reserve_id=r.reserve_id, offer_id=offer_id,
                                  rate_profile=state["placement"].rate_profile,
                                  commitment=runtime.context.commitments[cid] if cid else None)}


# ── graph ────────────────────────────────────────────────────────────────

def build_modify_graph():
    g = StateGraph(ModifyState, context_schema=AgentContext)
    g.add_node("validate_modify", validate_modify)
    g.add_node("recheck_capacity", recheck_capacity)
    g.add_node("ledger_replace", ledger_replace)
    g.add_node("sense_modify", sense_modify)
    g.add_node("ledger_restore", ledger_restore)
    g.add_node("record_modify", record_modify)
    g.add_node("respond", respond)
    g.add_edge(START, "validate_modify")
    g.add_conditional_edges("validate_modify", on_error("recheck_capacity"), ["recheck_capacity", "respond"])
    g.add_edge("recheck_capacity", "ledger_replace")
    g.add_conditional_edges("ledger_replace", on_error("sense_modify"), ["sense_modify", "respond"])
    g.add_conditional_edges("sense_modify", on_error("record_modify", "ledger_restore"),
                            ["record_modify", "ledger_restore"])
    g.add_edge("record_modify", "respond")
    g.add_edge("ledger_restore", "respond")
    g.add_edge("respond", END)
    return g.compile()
