"""Graph A · Protocol Graph: the scheduling agent's single entry point (slides 12, 19, 23).

Three nodes shared by every verb wrap the branches. ``dedupe_request`` answers a resent request from
the cache; ``sweep_expired`` reclaims whatever has expired (reclaim.py), so no branch sees it;
``route_verb`` dispatches the message to one of the branches, each a compiled subgraph in its own file;
``remember_response`` caches a successful reply for resends:

    START → dedupe_request ─ seen ─► END (the cached reply, or invalid_request if the body differs)
              │ new
              ▼
            sweep_expired → route_verb ─ quote   → quote.py    (step 4)   offers, nothing reserved
                                     ├ reserve → reserve.py  (step 5a)  debit the ledger, SENSE propagate
                                     ├ commit  → commit.py   (step 5a)  SENSE commit, confirm the ledger
                                     ├ release → release.py  (step 5b)  SENSE cancel, give back the bookings
                                     ├ modify  → modify.py   (step 5b)  change one offer's rate / time range
                                     └ unknown verb → END with an error
            (every branch) → remember_response → END

Idempotency: a request is identified by (verb, request_id), or (quote, quote_id). A resend with the same
body gets the cached reply and runs nothing, so a scheduling agent that lost a reply can simply send
again. Only successful replies are cached: after a failure, resending the same id retries for real.
Reusing an id for a different body is refused. Known gap: the cache is kept for the agent's lifetime;
pruning it (e.g. after a retry window) is a hook.

The parent state holds only the fields every branch shares (raw, now, response), plus the verb, what
the sweep reclaimed and whether the reply was replayed, which no branch reads. A subgraph receives the
shared fields it declares and returns only those to the parent, so each branch's intermediate fields
stay inside it.

Nodes only orchestrate: they decide what runs in which order and where data flows. The actual
computation and rules live in placement.py, ledger.py, estimate.py and circuit.py; a node takes its
inputs from state, calls those modules, and writes the results back to state. Shared objects such as
the ledger come from runtime.context (see context.py).
"""

from datetime import datetime
from typing import Literal, TypedDict, get_args

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import BaseModel, ValidationError

from ..context import AgentContext, Answered
from ..reclaim import SweepReport, sweep_expired
from ..schemas import (CommitAck, CommitRequest, ErrorResponse, ModifyAck, ModifyRequest, QuoteRequest,
                       QuoteResponse, ReleaseAck, ReleaseRequest, ReserveAck, ReserveRequest)
from .commit import build_commit_graph
from .modify import build_modify_graph
from .quote import build_quote_graph
from .release import build_release_graph
from .reserve import build_reserve_graph


Verb = Literal["quote", "reserve", "commit", "release", "modify"]

# verb → (request model, the field that identifies a request)
REQUESTS: dict[str, tuple[type[BaseModel], str]] = {
    "quote": (QuoteRequest, "quote_id"),
    "reserve": (ReserveRequest, "request_id"),
    "commit": (CommitRequest, "request_id"),
    "release": (ReleaseRequest, "request_id"),
    "modify": (ModifyRequest, "request_id"),
}


class ProtocolState(TypedDict, total=False):
    """Only the fields all branches share; each branch's own fields stay inside its subgraph."""

    verb: Verb                                    # input: which kind of message raw is
    raw: dict                                     # input
    now: datetime                                 # input
    replayed: bool                                # written by dedupe_request: the reply comes from the cache
    swept: SweepReport                            # written by sweep_expired
    response: QuoteResponse | ReserveAck | CommitAck | ReleaseAck | ModifyAck | ErrorResponse   # output


def _identify(state: ProtocolState) -> tuple[tuple[str, str], BaseModel] | None:
    """The request's cache key and parsed body; None if the verb is unknown or the body malformed (the
    branch or route_verb then answers with an error, which is never cached)."""
    verb, raw = state.get("verb"), state.get("raw")
    if verb not in REQUESTS:
        return None
    model, id_field = REQUESTS[verb]
    try:
        req = model.model_validate(raw)
    except ValidationError:
        return None
    return (verb, getattr(req, id_field)), req


def dedupe_request(state: ProtocolState, runtime: Runtime[AgentContext]) -> dict:
    """Answer a request already answered successfully, without running anything."""
    known = _identify(state)
    seen = runtime.context.answered.get(known[0]) if known else None
    if seen is None:
        return {}
    (verb, request_id), req = known
    if req != seen.request:
        return {"response": ErrorResponse(request_id=request_id, code="invalid_request",
                                          detail=f"{verb} {request_id} was already used for a different request")}
    return {"response": seen.response, "replayed": True}


def after_dedupe(state: ProtocolState) -> str:
    return END if "response" in state else "sweep_expired"


def sweep_expired_node(state: ProtocolState, runtime: Runtime[AgentContext]) -> dict:
    """Reclaim expired reservations, orphan instances and expired offers before any branch reads the books."""
    return {"swept": sweep_expired(runtime.context, state["now"])}


def route_verb(state: ProtocolState) -> dict:
    """Reject an unknown verb; otherwise do nothing, and the edge below picks the branch."""
    verb = state.get("verb")
    if verb in get_args(Verb):
        return {}
    raw = state.get("raw")
    request_id = (raw.get("request_id") or raw.get("quote_id")) if isinstance(raw, dict) else None
    return {"response": ErrorResponse(request_id=str(request_id or "unknown"), code="invalid_request",
                                      detail=f"unknown verb {verb!r}; expected one of {list(get_args(Verb))}")}


def after_route(state: ProtocolState) -> str:
    return END if "response" in state else state["verb"]


def remember_response(state: ProtocolState, runtime: Runtime[AgentContext]) -> dict:
    """Cache a successful reply under its request, for resends; errors are not cached."""
    if isinstance(state["response"], ErrorResponse):
        return {}
    key, req = _identify(state)
    runtime.context.answered[key] = Answered(req, state["response"])
    return {}


def build_protocol_graph():
    g = StateGraph(ProtocolState, context_schema=AgentContext)
    g.add_node("dedupe_request", dedupe_request)
    g.add_node("sweep_expired", sweep_expired_node)
    g.add_node("route_verb", route_verb)
    g.add_node("quote", build_quote_graph())
    g.add_node("reserve", build_reserve_graph())
    g.add_node("commit", build_commit_graph())
    g.add_node("release", build_release_graph())
    g.add_node("modify", build_modify_graph())
    g.add_node("remember_response", remember_response)
    g.add_edge(START, "dedupe_request")
    g.add_conditional_edges("dedupe_request", after_dedupe, ["sweep_expired", END])
    g.add_edge("sweep_expired", "route_verb")
    g.add_conditional_edges("route_verb", after_route, [*get_args(Verb), END])
    for verb in get_args(Verb):
        g.add_edge(verb, "remember_response")
    g.add_edge("remember_response", END)
    return g.compile()
