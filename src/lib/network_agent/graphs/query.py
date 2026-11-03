"""Graph A · query branch (step 4): offers for a bundle of transfers, without reserving anything.

    START → validate_bundle ─ok──► refresh_if_stale → find_placements → estimate_finish → respond → END
                            └fail────────────────────────────────────────────────────────► respond

A query is read-only: it reserves no capacity and never calls SENSE. Its only write is refreshing
stale ``observed`` values in the ledger, which are observations, not bookings. Every offer is also
remembered in offer_book, so that a later reserve can find what it refers to. The offers can be
reserved until valid_until (now + query_ttl_seconds); after that reserve refuses them and the expiry
sweep drops them from offer_book (step 5b).
"""

from datetime import datetime, timedelta
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from ..context import AgentContext, QueriedOffer
from ..placement import Placement, dedupe, search
from ..schemas import ErrorResponse, Offer, QueryRequest, QueryResponse, RejectReason, TransferQuery
from ..telemetry import refresh_stale
from ..topology import Path
from .common import parse_request


class QueryState(TypedDict, total=False):
    raw: dict                                     # input: the scheduling agent's request (JSON parsed into a dict)
    now: datetime                                 # input: current time, supplied by the caller (for tests and simulated clocks)
    request: QueryRequest                         # written by validate_bundle
    paths: dict[str, list[Path]]                  # written by refresh_if_stale: transfer_id → candidate paths
    refreshed: list[str]                          # written by refresh_if_stale: links refreshed this time
    placements: dict[str, list[Placement]]        # written by find_placements: feasible placements
    rejections: dict[str, RejectReason]           # written by find_placements: why a transfer is infeasible
    offers: dict[str, list[Offer]]                # written by estimate_finish
    response: QueryResponse | ErrorResponse       # output


# ── nodes ────────────────────────────────────────────────────────────────

def validate_bundle(state: QueryState) -> dict:
    """Check format and internal consistency only (the rules in schemas.py); whether the request can be met is left to later nodes."""
    req = parse_request(QueryRequest, state["raw"], id_field="query_id")
    return {"response": req} if isinstance(req, ErrorResponse) else {"request": req}


def refresh_if_stale(state: QueryState, runtime: Runtime[AgentContext]) -> dict:
    """Find candidate paths for each transfer; for observations on those paths that are stale within the
    window, pull fresh samples from telemetry once and write them into the ledger."""
    ctx, now = runtime.context, state["now"]
    paths: dict[str, list[Path]] = {}
    spans: list[tuple[Path, datetime, datetime]] = []
    for tr in state["request"].bundle:
        try:
            paths[tr.id] = ctx.topology.paths(tr.src, tr.dst, ctx.cfg.max_paths)
        except KeyError:                          # endpoint not in the topology: treat as "no path"
            paths[tr.id] = []
        start = max(tr.window.earliest_start, now)
        spans += [(path, start, tr.window.latest_finish) for path in paths[tr.id]]
    return {"paths": paths, "refreshed": refresh_stale(ctx.ledger, ctx.telemetry, spans, now)}


def find_placements(state: QueryState, runtime: Runtime[AgentContext]) -> dict:
    """Run placement.search once per transfer per candidate path; dedupe across paths, preferring shorter paths."""
    ctx = runtime.context
    placements: dict[str, list[Placement]] = {}
    rejections: dict[str, RejectReason] = {}
    for tr in state["request"].bundle:
        candidates = state["paths"][tr.id]
        if not candidates:
            rejections[tr.id] = RejectReason(cause="no_path", detail=f"no path from {tr.src} to {tr.dst}")
            continue
        found: list[Placement] = []
        reasons: list[RejectReason] = []
        for path in candidates:
            result = search(ctx.ledger, path, tr, state["now"], ctx.cfg.rate_step_gbps)
            if isinstance(result, RejectReason):
                reasons.append(result)
            else:
                found.extend(result)
        if found:
            placements[tr.id] = dedupe(found)
        else:
            rejections[tr.id] = reasons[0]        # report the shortest path's reason
    return {"placements": placements, "rejections": rejections}


def estimate_finish(state: QueryState, runtime: Runtime[AgentContext]) -> dict:
    """Placement → offer: estimate p50 / p95 finish times with the rate model."""
    req = state["request"]
    nbytes = {tr.id: tr.bytes for tr in req.bundle}
    offers: dict[str, list[Offer]] = {}
    for tid, ps in state["placements"].items():
        offers[tid] = []
        for k, p in enumerate(ps, start=1):
            p50, p95 = runtime.context.rate_model.predict_finish(p, nbytes[tid])
            offers[tid].append(Offer(
                offer_id=f"{req.query_id}/{tid}/{k}", transfer_id=tid,
                rate_profile=p.rate_profile,
                predicted_finish_p50=p50, predicted_finish_p95=p95, blocked_by=p.blocked_by))
    return {"offers": offers}


def respond(state: QueryState, runtime: Runtime[AgentContext]) -> dict:
    """Assemble the QueryResponse; record every offer in offer_book, so that reserve (step 5a) can look up
    by id the placement behind it and the request it answers."""
    if "response" in state:                       # validation failed; an ErrorResponse is already set
        return {}
    ctx, req = runtime.context, state["request"]
    valid_until = state["now"] + timedelta(seconds=ctx.cfg.query_ttl_seconds)
    results = []
    for tr in req.bundle:
        if tr.id in state["offers"]:
            offers = state["offers"][tr.id]
            for offer, p in zip(offers, state["placements"][tr.id]):
                ctx.offer_book[offer.offer_id] = QueriedOffer(req.query_id, tr, p, valid_until)
            results.append(TransferQuery(transfer_id=tr.id, status="feasible", offers=offers))
        else:
            reason = state["rejections"][tr.id]
            status = "unreachable" if reason.cause == "no_path" else "infeasible"
            results.append(TransferQuery(transfer_id=tr.id, status=status, reason=reason))
    return {"response": QueryResponse(query_id=req.query_id, mode=req.mode, results=results, valid_until=valid_until)}


# ── edges ────────────────────────────────────────────────────────────────

def after_validate(state: QueryState) -> str:
    return "respond" if "response" in state else "refresh_if_stale"


def build_query_graph():
    g = StateGraph(QueryState, context_schema=AgentContext)
    g.add_node("validate_bundle", validate_bundle)
    g.add_node("refresh_if_stale", refresh_if_stale)
    g.add_node("find_placements", find_placements)
    g.add_node("estimate_finish", estimate_finish)
    g.add_node("respond", respond)
    g.add_edge(START, "validate_bundle")
    g.add_conditional_edges("validate_bundle", after_validate, ["refresh_if_stale", "respond"])
    g.add_edge("refresh_if_stale", "find_placements")
    g.add_edge("find_placements", "estimate_finish")
    g.add_edge("estimate_finish", "respond")
    g.add_edge("respond", END)
    return g.compile()
