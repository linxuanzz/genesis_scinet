"""Step 4: the quote branch of graph A. The core case reproduces slide 7:

    T1 = 50 TB, window 09:00–15:00; ledger: only 40 Gbps left before 12:00, fully free 100 Gbps after.
    a1 09:00 @ 40 Gbps → 11:46:40   (slide says 13:47; the arithmetic gives 11:47)
    a2 12:00 @ 100 Gbps → 13:06:40  (slide 13:07)
    a3 09:00 @ 20 Gbps → 14:33:20   (slide 14:34)
"""

from datetime import timedelta

import pytest

from ..graphs.quote import build_quote_graph
from ..schemas import QuoteRequest, RateSegment
from .helpers import L2, MAIN, make_ctx, make_net, quote, t, tr
from .printing import hops, print_network


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    return make_ctx(net)


@pytest.fixture
def graph():
    return build_quote_graph()


def summary(offer):
    seg = offer.rate_profile[0]
    return seg.start, seg.gbps, offer.predicted_finish_p50


# ── slide 7 ──────────────────────────────────────────────────────────────

def test_slide7_three_offers(graph, ctx):
    resp = quote(graph, ctx, tr())["response"]
    assert resp.admissible
    offers = resp.results[0].offers
    assert [summary(o) for o in offers] == [
        (t(9), 40, t(11, 46) + timedelta(seconds=40)),
        (t(12), 100, t(13, 6) + timedelta(seconds=40)),
        (t(9), 20, t(14, 33) + timedelta(seconds=20)),
    ]
    assert [o.blocked_by for o in offers] == ["background_traffic", None, None]
    assert [o.offer_id for o in offers] == ["q1/T1/1", "q1/T1/2", "q1/T1/3"]


def test_offers_are_kept_for_reserve(graph, ctx):
    quote(graph, ctx, tr())
    assert set(ctx.offer_book) == {"q1/T1/1", "q1/T1/2", "q1/T1/3"}
    kept = ctx.offer_book["q1/T1/2"]
    assert (kept.quote_id, kept.placement.path) == ("q1", MAIN)
    assert kept.request == tr()                   # the original request, for the commitment's workflow_id


# ── refresh_if_stale ─────────────────────────────────────────────────────

def test_refresh_pulls_telemetry_into_ledger(graph, ctx):
    assert ctx.ledger.observed(L2, 0).source == "topology"
    out = quote(graph, ctx, tr())
    assert L2 in out["refreshed"]
    assert (ctx.ledger.observed(L2, 0).gbps, ctx.ledger.observed(L2, 0).source) == (40, "mock")
    assert ctx.telemetry.calls == 1


def test_fresh_values_are_not_refetched(graph, ctx):
    quote(graph, ctx, tr())
    out = quote(graph, ctx, tr(), now=t(9, 1))    # samples are valid for 5 minutes, still fresh after 1
    assert out["refreshed"] == [] and ctx.telemetry.calls == 1


def test_quote_is_read_only(graph, ctx):
    quote(graph, ctx, tr())
    assert all(ctx.ledger.own(link, i) == 0 for link in MAIN for i in range(ctx.ledger.n_slots))


# ── blocked_by: blocked by our own bookings ───────────────────────────────

def test_blocked_by_own_commitment(net, graph, ctx):
    """Remove background traffic and book 30 ourselves on the main path instead: the earliest start can only get 70, because of own_commitment."""
    net._background[L2].clear()
    ctx.ledger.pending("ours", MAIN, [RateSegment(start=t(9), end=t(12), gbps=30)])
    first = quote(graph, ctx, tr())["response"].results[0].offers[0]
    assert (first.rate_profile[0].gbps, first.blocked_by) == (70, "own_commitment")


# ── the four rejection cases ──────────────────────────────────────────────

@pytest.mark.parametrize("transfer, status, cause", [
    (tr(dst="mars"), "unreachable", "no_path"),
    (tr(window=(t(9), t(9, 30))), "infeasible", "no_capacity"),                    # 50 TB in 30 minutes
    (tr(window=(t(10, day=21), t(12, day=21))), "infeasible", "beyond_horizon"),    # the ledger only reaches 09:00 next day
    (tr(nbytes=10 * 10**12, window=(t(9), t(11)), min_useful_rate_gbps=60),             # 40 Gbps would finish,
     "infeasible", "below_min_useful_rate"),                                          # but is below the declared 60
])
def test_rejections(graph, ctx, transfer, status, cause):
    result = quote(graph, ctx, transfer)["response"].results[0]
    assert (result.status, result.reason.cause) == (status, cause)


def test_now_clips_earliest_start(graph, ctx):
    offers = quote(graph, ctx, tr(), now=t(10, 5))["response"].results[0].offers
    assert min(o.rate_profile[0].start for o in offers) == t(10, 5)


# ── bundle and mode ───────────────────────────────────────────────────────

def test_mode_decides_admissible(graph, ctx):
    bundle = [tr(), tr(id="T2", dst="mars")]
    assert not quote(graph, ctx, *bundle, mode="all_or_nothing")["response"].admissible
    assert quote(graph, ctx, *bundle, mode="best_subset")["response"].admissible


# ── exit for failed validation ────────────────────────────────────────────

def test_invalid_request_goes_straight_to_respond(graph, ctx):
    raw = QuoteRequest(quote_id="q9", bundle=[tr()], mode="best_subset").model_dump()
    raw["bundle"][0]["window"] = {"earliest_start": t(15), "latest_finish": t(9)}   # window reversed
    out = graph.invoke({"raw": raw, "now": t(9)}, context=ctx)
    assert (out["response"].code, out["response"].request_id) == ("invalid_request", "q9")
    assert "refreshed" not in out and ctx.telemetry.calls == 0


def test_graph_shape(graph):
    nodes = set(graph.get_graph().nodes)
    assert {"validate_bundle", "refresh_if_stale", "find_placements", "estimate_finish", "respond"} <= nodes


# ── demo: print the full scenario and quote result ────────────────────────
#
# How to run (from the repository root), with one scenario as the argument:
#   python -m <package path>.tests.test_step4_quote_graph test1     (e.g. network_agent.tests...)
# scenarios: test1 / test2 / test3

SCENARIOS = {
    "test1": ("Slide 7 as drawn: background traffic takes 60 Gbps on L2 until 12:00; deadline 15:00", dict(background_gbps=60, deadline=t(15))),
    "test2": ("Variant 1: background traffic takes only 20 Gbps (80 Gbps left until 12:00)", dict(background_gbps=20, deadline=t(15))),
    "test3": ("Variant 2: deadline moved up to 13:00", dict(background_gbps=60, deadline=t(13))),
}


def availability_runs(ledger, path, start, end):
    """A path's available capacity over [start, end), merging adjacent equal runs: [(start, end, Gbps, bottleneck link)]."""
    runs = []
    for i in ledger.slots_covering(start, end):
        gbps, link = ledger.path_available(path, i)
        a, b = ledger.slot_start(i), ledger.slot_start(i + 1)
        if runs and runs[-1][2:] == (gbps, link):
            runs[-1] = (runs[-1][0], b, gbps, link)
        else:
            runs.append((a, b, gbps, link))
    return runs


def print_scenario(title, net, ctx, req, now, out):
    topo = net.topology
    print_network(title, net)

    print(f"\nRequest {req.quote_id} (mode={req.mode}), now = {now:%H:%M}:")
    for tr_ in req.bundle:
        w = tr_.window
        print(f"  {tr_.id}: {tr_.src} → {tr_.dst}, {tr_.bytes / 1e12:g} TB, "
              f"window {w.earliest_start:%H:%M}–{w.latest_finish:%H:%M}")

    print("\nCandidate paths, with available capacity per time range after refresh (narrowest hop):")
    path_no = {}
    for tr_ in req.bundle:
        for k, path in enumerate(out["paths"][tr_.id], start=1):
            path_no[path] = k
            print(f"  path{k}: {hops(topo, path)}")
            for a, b, gbps, link in availability_runs(ctx.ledger, path, tr_.window.earliest_start,
                                                      min(tr_.window.latest_finish, ctx.ledger.horizon_end)):
                print(f"      {a:%H:%M}–{b:%H:%M}   {gbps:>5g} Gbps   bottleneck {link}")
    print("Links refreshed:", out["refreshed"])

    resp = out["response"]
    print(f"\nQuote result: admissible = {resp.admissible}")
    for r in resp.results:
        if r.status != "feasible":
            print(f"  {r.transfer_id}: {r.status} ({r.reason.cause}: {r.reason.detail})")
        for o in r.offers:
            s, p = o.rate_profile[0], ctx.offer_book[o.offer_id].placement   # the path and rule are not exposed externally
            print(f"  {o.offer_id}: start {s.start:%H:%M} @ {s.gbps:>5g} Gbps → finish {o.predicted_finish_p50:%H:%M:%S}"
                  f"   [path{path_no[p.path]}, rule {p.strategy}]   blocked_by={o.blocked_by}")


def demo(title=SCENARIOS["test1"][0], background_gbps=60, deadline=t(15)):
    net = make_net(background_gbps)
    ctx = make_ctx(net)
    transfer = tr(window=(t(9), deadline))
    out = quote(build_quote_graph(), ctx, transfer)
    req = QuoteRequest(quote_id="q1", bundle=[transfer], mode="all_or_nothing")
    print_scenario(title, net, ctx, req, t(9), out)
    return out


def test_demo_printout():
    for title, kwargs in SCENARIOS.values():
        assert demo(title, **kwargs)["response"].admissible


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        print(f"Usage: python -m {__spec__.name} <scenario>")
        for name, (title, _) in SCENARIOS.items():
            print(f"  {name}   {title}")
        sys.exit(1)
    title, kwargs = SCENARIOS[sys.argv[1]]
    demo(title, **kwargs)
