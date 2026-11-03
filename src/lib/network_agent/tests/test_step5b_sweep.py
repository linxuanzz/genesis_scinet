"""Step 5b: the expiry sweep (reclaim.sweep_expired) and the quote's validity.

Same quoted agent as the release tests: q1 was quoted at 09:00 and is valid until 09:15
(quote_ttl_seconds 900); a reservation made at 09:00 expires at 09:01 (reserve_ttl_seconds 60).
"""

import pytest

from ..graphs.protocol import build_protocol_graph
from ..reclaim import SweepReport, sweep_expired
from ..schemas import CommitAck, QuoteRequest, ReserveRequest
from .helpers import L2, MAIN, commit, make_ctx, make_net, make_quoted_ctx, release, reserve, t, tr

PAIR = ("q1/T1/2", "q1/T2/1")


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    return make_quoted_ctx(net)


def own_total(ctx):
    return sum(ctx.ledger.own(link, i) for link in MAIN for i in range(ctx.ledger.n_slots))


# ── expired reservations ──────────────────────────────────────────────────

def test_nothing_to_sweep_before_expiry(net, ctx):
    reserve(ctx, *PAIR)
    assert sweep_expired(ctx, t(9)) == SweepReport()
    assert ctx.reservations["rsv-1"].state == "reserved" and len(net._ours) == 2


def test_expired_reservation_is_reclaimed(net, ctx):
    reserve(ctx, *PAIR)
    assert sweep_expired(ctx, t(9, 1)).expired == ["rsv-1"]
    assert ctx.reservations["rsv-1"].state == "expired"
    assert own_total(ctx) == 0 and net._ours == {}
    assert [ctx.sense.state(i).state for i in ("si-1", "si-2")] == ["cancelled", "cancelled"]
    assert sweep_expired(ctx, t(9, 2)) == SweepReport()                     # nothing left the second time


def test_committed_reservation_never_expires(net, ctx):
    reserve(ctx, *PAIR)
    commit(ctx)
    report = sweep_expired(ctx, t(10))
    assert (report.expired, report.stuck) == ([], {})                       # only q1's offers go
    assert ctx.reservations["rsv-1"].state == "committed" and own_total(ctx) > 0


def test_after_the_sweep(ctx):
    """commit says expired (not conflict); release has nothing left; the offers can be reserved again."""
    reserve(ctx, *PAIR)
    sweep_expired(ctx, t(9, 1))
    assert commit(ctx, now=t(9, 1))["response"].code == "expired"
    resp = release(ctx, now=t(9, 1))["response"]
    assert resp.code == "conflict" and "expired" in resp.detail
    assert reserve(ctx, *PAIR, now=t(9, 1))["response"].reserve_id == "rsv-2"


def test_failed_cancel_is_retried_by_the_next_sweep(net, ctx):
    reserve(ctx, *PAIR)
    ctx.sense.fail_next("cancel")                                           # si-1 (q1/T1/2) fails once
    report = sweep_expired(ctx, t(9, 1))
    assert report.expired == [] and report.stuck == {"rsv-1": ["q1/T1/2"]}
    r = ctx.reservations["rsv-1"]
    assert r.state == "reserved" and [i.offer_id for i in r.held] == ["q1/T1/2"]
    assert ctx.ledger.booking("rsv-1/q1/T1/2").state == "pending"           # the network still carries it
    assert commit(ctx, now=t(9, 1))["response"].code == "expired"

    assert sweep_expired(ctx, t(9, 2)).expired == ["rsv-1"]
    assert own_total(ctx) == 0 and net._ours == {}


# ── orphan instances ──────────────────────────────────────────────────────

def test_orphan_from_a_failed_rollback_is_cancelled(net, ctx):
    """SENSE refuses q1/T1/2 and the rollback fails to cancel si-1 (q1/T2/1): si-1 is an orphan that keeps
    its booking until a sweep manages to cancel it."""
    net.add_background(L2, t(12), t(13), 30)
    ctx.sense.fail_next("cancel")
    reserve(ctx, "q1/T2/1", "q1/T1/2", now=t(9, 1))
    assert ctx.orphans == {"si-1": "rsv-1/q1/T2/1"} and own_total(ctx) > 0

    assert sweep_expired(ctx, t(9, 1)).orphans == ["si-1"]
    assert ctx.orphans == {} and own_total(ctx) == 0 and net._ours == {}


def test_orphan_cancel_failing_again_waits(ctx, net):
    net.add_background(L2, t(12), t(13), 30)
    ctx.sense.fail_next("cancel", times=2)
    reserve(ctx, "q1/T2/1", "q1/T1/2", now=t(9, 1))
    assert sweep_expired(ctx, t(9, 1)).orphans == []
    assert ctx.orphans == {"si-1": "rsv-1/q1/T2/1"}
    assert sweep_expired(ctx, t(9, 2)).orphans == ["si-1"]


# ── quote validity ────────────────────────────────────────────────────────

def test_quote_carries_its_validity(net):
    ctx, graph = make_ctx(net), build_protocol_graph()
    out = graph.invoke({"verb": "quote", "raw": QuoteRequest(quote_id="q1", bundle=[tr()], mode="all_or_nothing")
                        .model_dump(), "now": t(9)}, context=ctx)
    assert out["response"].valid_until == t(9, 15)
    assert {q.expires_at for q in ctx.offer_book.values()} == {t(9, 15)}


def test_expired_offers_are_dropped(ctx):
    assert sweep_expired(ctx, t(9, 14)).quotes == []
    assert sweep_expired(ctx, t(9, 15)).quotes == ["q1"]
    assert ctx.offer_book == {} and ctx.expired_quotes == {"q1"}


@pytest.mark.parametrize("swept", [False, True])
def test_reserve_after_the_quote_expired(ctx, swept):
    """Refused as expired whether or not the sweep has dropped the offers yet."""
    if swept:
        sweep_expired(ctx, t(9, 15))
    resp = reserve(ctx, "q1/T1/1", now=t(9, 15))["response"]
    assert resp.code == "expired" and "q1" in resp.detail
    assert ctx.reservations == {}


def test_commit_after_the_quote_was_dropped(ctx):
    """The commitment's transfer and workflow come from the reservation, not from offer_book."""
    reserve(ctx, "q1/T1/2", ttl_seconds=1800)                               # held until 09:30
    sweep_expired(ctx, t(9, 20))
    assert ctx.offer_book == {}
    resp = commit(ctx, now=t(9, 20))["response"]
    assert isinstance(resp, CommitAck)
    assert [(c.transfer_id, c.workflow_id) for c in resp.commitments] == [("T1", "WF-1")]


# ── through graph A ───────────────────────────────────────────────────────

def test_graph_a_sweeps_before_every_message(net):
    """An expired reservation is reclaimed by the next message of any kind, so the quote it carries
    already sees the capacity again."""
    ctx, graph = make_ctx(net), build_protocol_graph()

    def send(verb, msg, now):
        return graph.invoke({"verb": verb, "raw": msg.model_dump(), "now": now}, context=ctx)

    send("quote", QuoteRequest(quote_id="q1", bundle=[tr()], mode="all_or_nothing"), t(9))
    send("reserve", ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T1/2"]), t(9))
    out = send("quote", QuoteRequest(quote_id="q2", bundle=[tr("T2")], mode="all_or_nothing"), t(9, 1))
    assert out["swept"].expired == ["rsv-1"]
    noon = [o for o in out["response"].results[0].offers if o.start == t(12)]
    assert noon and noon[0].rate_profile[0].gbps == 100                      # 12:00 @ 100 Gbps is free again
