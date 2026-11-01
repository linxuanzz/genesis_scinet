"""Graph A · Protocol Graph: the scheduling agent's single entry point (slides 12, 19, 23).

``route_verb`` dispatches each message to one of three branches; each branch is a compiled subgraph
in its own file:

    START → route_verb ─ quote   → quote.py    (step 4)   offers, nothing reserved
                       ├ reserve → reserve.py  (step 5a)  debit the ledger, SENSE propagate
                       ├ commit  → commit.py   (step 5a)  SENSE commit, confirm the ledger
                       └ unknown verb → END with an error

The parent state holds only the fields every branch shares (raw, now, response) plus the verb. A
subgraph receives the shared fields it declares and returns only those to the parent, so each
branch's intermediate fields stay inside it.

Nodes only orchestrate: they decide what runs in which order and where data flows. The actual
computation and rules live in placement.py, ledger.py, estimate.py and circuit.py; a node takes its
inputs from state, calls those modules, and writes the results back to state. Shared objects such as
the ledger come from runtime.context (see context.py).
"""

from datetime import datetime
from typing import Literal, TypedDict, get_args

from langgraph.graph import END, START, StateGraph

from ..context import AgentContext
from ..schemas import CommitAck, ErrorResponse, QuoteResponse, ReserveAck
from .commit import build_commit_graph
from .quote import build_quote_graph
from .reserve import build_reserve_graph


Verb = Literal["quote", "reserve", "commit"]


class ProtocolState(TypedDict, total=False):
    """Only the fields all branches share; each branch's own fields stay inside its subgraph."""

    verb: Verb                                    # input: which kind of message raw is
    raw: dict                                     # input
    now: datetime                                 # input
    response: QuoteResponse | ReserveAck | CommitAck | ErrorResponse   # output


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


def build_protocol_graph():
    g = StateGraph(ProtocolState, context_schema=AgentContext)
    g.add_node("route_verb", route_verb)
    g.add_node("quote", build_quote_graph())
    g.add_node("reserve", build_reserve_graph())
    g.add_node("commit", build_commit_graph())
    g.add_edge(START, "route_verb")
    g.add_conditional_edges("route_verb", after_route, [*get_args(Verb), END])
    for verb in get_args(Verb):
        g.add_edge(verb, END)
    return g.compile()
