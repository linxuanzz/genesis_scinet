"""Step 5b: the release branch of graph A.

Starts from the same queried agent as the 5a tests (helpers.make_queried_ctx). Most tests reserve two
offers together: q1/T1/2 (12:00 @ 100 Gbps, instance si-1) and q1/T2/1 (09:00 @ 40 Gbps, si-2).
"""

import pytest

from ..graphs.protocol import build_protocol_graph
from ..schemas import CommitAck, QueryRequest, ReleaseAck, ReleaseRequest, ReserveAck, ReserveRequest
from ..sense import SenseError
from .helpers import MAIN, commit, make_ctx, make_net, make_queried_ctx, release, reserve, t, tr

PAIR = ("q1/T1/2", "q1/T2/1")


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    return make_queried_ctx(net)


def own_on_main(ctx, hh, mm=0):
    """Our own bookings on the main path in the slot starting at hh:mm."""
    i = ctx.ledger.slots_covering(t(hh, mm), t(hh, mm + 1))[0]
    return [ctx.ledger.own(link, i) for link in MAIN]


def assert_all_given_back(net, ctx):
    assert all(ctx.ledger.own(link, i) == 0 for link in MAIN for i in range(ctx.ledger.n_slots))
    assert net._ours == {}


# ── success ───────────────────────────────────────────────────────────────

def test_release_reserved(net, ctx):
    reserve(ctx, *PAIR)
    resp = release(ctx)["response"]
    assert resp == ReleaseAck(reserve_id="rsv-1", offer_ids=list(PAIR))
    assert_all_given_back(net, ctx)
    assert [ctx.sense.state(i).state for i in ("si-1", "si-2")] == ["cancelled", "cancelled"]
    assert ctx.reservations["rsv-1"].state == "released"


def test_release_committed_drops_commitments(net, ctx):
    reserve(ctx, *PAIR)
    commit(ctx)
    assert release(ctx)["response"].offer_ids == list(PAIR)
    assert_all_given_back(net, ctx)
    assert ctx.commitments == {}


def test_partial_release_keeps_the_rest(net, ctx):
    """T2 finished early: give back its 09:00 slot, T1 keeps its circuit."""
    reserve(ctx, *PAIR)
    commit(ctx)
    assert release(ctx, offer_ids=["q1/T2/1"])["response"].offer_ids == ["q1/T2/1"]
    assert own_on_main(ctx, 9) == [0, 0, 0]
    assert own_on_main(ctx, 12) == [100, 100, 100]
    r = ctx.reservations["rsv-1"]
    assert r.state == "committed" and [i.offer_id for i in r.held] == ["q1/T1/2"]
    assert [c.transfer_id for c in ctx.commitments.values()] == ["T1"]
    assert list(net._ours) == ["si-1"]


def test_commit_after_partial_release_commits_the_rest(ctx):
    reserve(ctx, *PAIR)
    release(ctx, offer_ids=["q1/T2/1"])
    resp = commit(ctx)["response"]
    assert isinstance(resp, CommitAck) and [c.transfer_id for c in resp.commitments] == ["T1"]


def test_released_offer_can_be_reserved_again(ctx):
    reserve(ctx, "q1/T1/2")
    release(ctx)
    assert reserve(ctx, "q1/T1/2")["response"] == ReserveAck(reserve_id="rsv-2", offer_ids=["q1/T1/2"],
                                                            expires_at=t(9, 1))


# ── rejected ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("over, code", [
    ({"reserve_id": "rsv-9"}, "not_found"),                       # no such reservation
    ({"offer_ids": ["q1/T1/1"]}, "not_found"),                    # queried, but not in rsv-1
])
def test_unknown_target(net, ctx, over, code):
    reserve(ctx, *PAIR)
    assert release(ctx, **over)["response"].code == code
    assert ctx.reservations["rsv-1"].held == ctx.reservations["rsv-1"].items


def test_cannot_release_twice(ctx):
    reserve(ctx, *PAIR)
    release(ctx, offer_ids=["q1/T2/1"])
    assert release(ctx, offer_ids=["q1/T2/1"])["response"].code == "conflict"
    release(ctx)                                                   # the rest
    assert release(ctx)["response"].code == "conflict"


def test_commit_after_full_release_is_refused(ctx):
    reserve(ctx, *PAIR)
    release(ctx)
    resp = commit(ctx)["response"]
    assert resp.code == "conflict" and "released" in resp.detail


def test_empty_offer_list_is_malformed():
    with pytest.raises(ValueError):
        ReleaseRequest(request_id="x1", reserve_id="rsv-1", offer_ids=[])


# ── SENSE fails to cancel ─────────────────────────────────────────────────

def test_failed_cancel_keeps_that_item(net, ctx):
    """si-1 fails to cancel, si-2 succeeds: q1/T2/1 is given back, q1/T1/2 stays held (booking and all);
    retrying finishes the job."""
    reserve(ctx, *PAIR)
    ctx.sense.fail_next("cancel")
    resp = release(ctx)["response"]
    assert resp.code == "sense_failure"
    assert "still held: ['q1/T1/2" in resp.detail and "released: ['q1/T2/1']" in resp.detail
    r = ctx.reservations["rsv-1"]
    assert r.state == "reserved" and [i.offer_id for i in r.held] == ["q1/T1/2"]
    assert ctx.ledger.booking("rsv-1/q1/T1/2").state == "pending"
    assert list(net._ours) == ["si-1"]

    assert release(ctx)["response"] == ReleaseAck(reserve_id="rsv-1", offer_ids=["q1/T1/2"])
    assert_all_given_back(net, ctx)


def test_unknown_instance_is_a_sense_error(ctx):
    with pytest.raises(SenseError) as e:
        ctx.sense.state("si-9")
    assert e.value.reason == "not_found"


# ── through graph A ───────────────────────────────────────────────────────

def test_release_through_protocol_graph(net):
    ctx, graph = make_ctx(net), build_protocol_graph()

    def send(verb, msg):
        return graph.invoke({"verb": verb, "raw": msg.model_dump(), "now": t(9)}, context=ctx)

    send("query", QueryRequest(query_id="q1", bundle=[tr()], mode="all_or_nothing"))
    send("reserve", ReserveRequest(request_id="r1", query_id="q1", offer_ids=["q1/T1/2"]))
    out = send("release", ReleaseRequest(request_id="x1", reserve_id="rsv-1"))
    assert out["response"] == ReleaseAck(reserve_id="rsv-1", offer_ids=["q1/T1/2"])
    assert_all_given_back(net, ctx)
