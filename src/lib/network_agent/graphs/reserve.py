"""Graph A · reserve branch (step 5a): tentatively reserve the offers the scheduling agent chose (``hold`` in the slides).

    START → validate_reserve ─fail─► respond
              │ ok
              ▼
            recheck_capacity → place_on_circuit → compile_intent → ledger_pending ─fail─► respond
                                                                     │ ok
                                                                     ▼
                                                                   sense_propagate ─fail─► ledger_rollback → respond
                                                                     │ ok
                                                                     ▼
                                                                   record_reserve → respond → END

A reserve is all or nothing for the whole group of offers (slide 19: one hold for the whole group):
the ledger debits them together, and if SENSE refuses any one, the instances already created are
cancelled and every booking is rolled back.

Each offer gets its own circuit, i.e. one ServiceIntent and one SENSE instance (see circuit.py). The
debit happens here, not at commit, so that the very next quote already sees it; commit only confirms.

An offer can only be reserved within its quote's validity. A reservation past its expires_at is
reclaimed by the expiry sweep (reclaim.py), as are instances a rollback failed to cancel: those keep
their bookings until then, since the network still carries them. A resent request_id is answered from
graph A's cache (protocol.py); this branch alone does not recognize it.
"""

from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from ..circuit import compile_intent, place_on_circuit
from ..context import AgentContext, QuotedOffer, Reservation, ReservedOffer
from ..ledger import InsufficientCapacity
from ..placement import Placement
from ..schemas import ErrorResponse, ReserveAck, ReserveRequest, ServiceIntent, ServiceState
from ..sense import SenseError, cancel_instances
from ..telemetry import refresh_stale
from .common import on_error, parse_request


class ReserveState(TypedDict, total=False):
    raw: dict                                     # input: the scheduling agent's ReserveRequest as a dict
    now: datetime                                 # input: current time
    request: ReserveRequest                       # written by validate_reserve
    reserve_id: str                               # written by validate_reserve
    quoted: dict[str, QuotedOffer]                # written by validate_reserve: offer_id → what was quoted, in request order
    refreshed: list[str]                          # written by recheck_capacity: links refreshed this time
    chosen: dict[str, Placement]                  # written by place_on_circuit: offer_id → placement to book
    intents: dict[str, ServiceIntent]             # written by compile_intent
    bookings: dict[str, str]                      # written by ledger_pending: offer_id → ledger booking id
    instances: dict[str, ServiceState]            # written by sense_propagate: offer_id → SENSE instance (only those created)
    error: ErrorResponse                          # written by whichever node fails
    response: ReserveAck | ErrorResponse          # output


# ── nodes ────────────────────────────────────────────────────────────────

def validate_reserve(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    """Check the request against what we quoted and what is already reserved. Nothing is written yet."""
    ctx, req = runtime.context, parse_request(ReserveRequest, state["raw"])
    if isinstance(req, ErrorResponse):
        return {"error": req}

    def fail(code: str, detail: str) -> dict:
        return {"request": req, "error": ErrorResponse(request_id=req.request_id, code=code, detail=detail)}

    unknown = [o for o in req.offer_ids if o not in ctx.offer_book]
    if unknown and req.quote_id in ctx.expired_quotes:
        return fail("expired", f"quote {req.quote_id} has expired; its offers were dropped")
    if unknown:
        return fail("not_found", f"unknown offers: {unknown}")
    quoted = {o: ctx.offer_book[o] for o in req.offer_ids}
    stale = [o for o, q in quoted.items() if state["now"] >= q.expires_at]
    if stale:
        return fail("expired", f"offers whose quote expired at {quoted[stale[0]].expires_at:%H:%M:%S}: {stale}")
    other_quote = [o for o, q in quoted.items() if q.quote_id != req.quote_id]
    if other_quote:
        return fail("invalid_request", f"offers not from quote {req.quote_id}: {other_quote}")
    transfers = [q.request.id for q in quoted.values()]
    twice = sorted({tid for tid in transfers if transfers.count(tid) > 1})
    if twice:
        return fail("invalid_request", f"more than one offer for transfers {twice}")
    taken = sorted(item.offer_id for r in ctx.reservations.values() for item in r.held if item.offer_id in quoted)
    if taken:
        return fail("conflict", f"offers already reserved: {taken}")
    over = [o for o, q in quoted.items() if q.placement.end <= state["now"]]
    if over:
        return fail("expired", f"offers whose time range has already passed: {over}")
    return {"request": req, "quoted": quoted, "reserve_id": ctx.new_id("rsv")}


def recheck_capacity(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    """Refresh stale observations on the offers' paths, so that the debit below is checked against current
    numbers rather than those seen at quote time. The check itself is ledger_pending's atomic
    check-then-write, which also covers offers in the group that share a link."""
    ctx = runtime.context
    spans = [(q.placement.path, q.placement.start, q.placement.end) for q in state["quoted"].values()]
    return {"refreshed": refresh_stale(ctx.ledger, ctx.telemetry, spans, state["now"])}


def place_on_circuit_node(state: ReserveState) -> dict:
    """Decide which circuit carries each offer. Step 5a: a new circuit per offer, on the quoted path.
    Extension hooks (warm-circuit reuse, alternate path, priority / preemption): see circuit.place_on_circuit."""
    return {"chosen": {o: place_on_circuit(q.placement) for o, q in state["quoted"].items()}}


def compile_intent_node(state: ReserveState) -> dict:
    """One ServiceIntent per offer; the alias ties the SENSE instance back to this reservation."""
    rid = state["reserve_id"]
    return {"intents": {o: compile_intent(p, state["quoted"][o].request.src, state["quoted"][o].request.dst,
                                          alias=f"{rid}/{o}")
                        for o, p in state["chosen"].items()}}


def ledger_pending(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    """Debit the whole group in the own layer at once; if any offer no longer fits, nothing is debited."""
    rid = state["reserve_id"]
    bookings = {o: f"{rid}/{o}" for o in state["chosen"]}
    try:
        runtime.context.ledger.pending_group([(bookings[o], p.path, p.rate_profile) for o, p in state["chosen"].items()])
    except InsufficientCapacity as e:
        return {"error": ErrorResponse(request_id=state["request"].request_id, code="conflict",
                                       detail=f"capacity no longer available: {e}")}
    return {"bookings": bookings}


def sense_propagate(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    """Ask SENSE to hold each intent (propagate). Stops at the first failure; the instances created so far
    are recorded so that ledger_rollback can cancel them."""
    instances: dict[str, ServiceState] = {}
    for o, intent in state["intents"].items():
        try:
            instances[o] = runtime.context.sense.propagate(intent, state["now"])
        except SenseError as e:
            return {"instances": instances,
                    "error": ErrorResponse(request_id=state["request"].request_id, code="sense_failure",
                                           detail=f"{o}: {e}")}
    return {"instances": instances}


def ledger_rollback(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    """Undo the whole reserve: cancel the SENSE instances already created, then return the bookings. An
    instance that fails to cancel becomes an orphan: it keeps its booking until the expiry sweep cancels it."""
    ctx, instances = runtime.context, state["instances"]
    _, failed = cancel_instances(ctx.sense, [s.instance_id for s in instances.values()], state["now"])
    for o, booking_id in state["bookings"].items():
        if o in instances and instances[o].instance_id in failed:
            ctx.orphans[instances[o].instance_id] = booking_id
        else:
            ctx.ledger.rollback(booking_id)
    if failed:
        stuck = [f"{instance_id} ({e})" for instance_id, e in failed.items()]
        error = state["error"]
        return {"error": error.model_copy(update={"detail": f"{error.detail}; cancel also failed: {stuck}, "
                                                            "kept until the expiry sweep cancels it"})}
    return {}


def record_reserve(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    """Write the reservation into the context, with its expiry."""
    ctx, req, rid = runtime.context, state["request"], state["reserve_id"]
    ttl = req.ttl_seconds or ctx.cfg.reserve_ttl_seconds
    items = [ReservedOffer(offer_id=o, request=state["quoted"][o].request, placement=state["chosen"][o],
                           booking_id=state["bookings"][o], intent=state["intents"][o],
                           instance_id=s.instance_id, vlan=s.vlan)
             for o, s in state["instances"].items()]
    ctx.reservations[rid] = Reservation(reserve_id=rid, quote_id=req.quote_id, items=items,
                                        expires_at=state["now"] + timedelta(seconds=ttl))
    return {}


def respond(state: ReserveState, runtime: Runtime[AgentContext]) -> dict:
    if "error" in state:
        return {"response": state["error"]}
    r = runtime.context.reservations[state["reserve_id"]]
    return {"response": ReserveAck(reserve_id=r.reserve_id, offer_ids=[i.offer_id for i in r.items],
                                   expires_at=r.expires_at)}


# ── edges ────────────────────────────────────────────────────────────────

def build_reserve_graph():
    g = StateGraph(ReserveState, context_schema=AgentContext)
    g.add_node("validate_reserve", validate_reserve)
    g.add_node("recheck_capacity", recheck_capacity)
    g.add_node("place_on_circuit", place_on_circuit_node)
    g.add_node("compile_intent", compile_intent_node)
    g.add_node("ledger_pending", ledger_pending)
    g.add_node("sense_propagate", sense_propagate)
    g.add_node("ledger_rollback", ledger_rollback)
    g.add_node("record_reserve", record_reserve)
    g.add_node("respond", respond)
    g.add_edge(START, "validate_reserve")
    g.add_conditional_edges("validate_reserve", on_error("recheck_capacity"), ["recheck_capacity", "respond"])
    g.add_edge("recheck_capacity", "place_on_circuit")
    g.add_edge("place_on_circuit", "compile_intent")
    g.add_edge("compile_intent", "ledger_pending")
    g.add_conditional_edges("ledger_pending", on_error("sense_propagate"), ["sense_propagate", "respond"])
    g.add_conditional_edges("sense_propagate", on_error("record_reserve", "ledger_rollback"),
                            ["record_reserve", "ledger_rollback"])
    g.add_edge("record_reserve", "respond")
    g.add_edge("ledger_rollback", "respond")
    g.add_edge("respond", END)
    return g.compile()
