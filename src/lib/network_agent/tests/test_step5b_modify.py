"""Step 5b: the modify branch of graph A.

Same quoted agent as the 5a tests. The offers used here:

    q1/T1/1  09:00–11:46:40 @  40 Gbps   (L2 has 40 left before 12:00: background 60)
    q1/T1/2  12:00–13:06:40 @ 100 Gbps
"""

from datetime import timedelta

import pytest

from ..graphs.modify import build_modify_graph
from ..graphs.protocol import build_protocol_graph
from ..ledger import InsufficientCapacity
from ..schemas import CommitAck, ModifyAck, ModifyRequest, QuoteRequest, RateSegment, ReserveRequest
from .helpers import L2, MAIN, commit, make_ctx, make_net, make_quoted_ctx, modify, release, reserve, t, tr


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    return make_quoted_ctx(net)


def own_on_main(ctx, hh, mm=0):
    i = ctx.ledger.slots_covering(t(hh, mm), t(hh, mm + 1))[0]
    return [ctx.ledger.own(link, i) for link in MAIN]


def in_sense(net, instance_id="si-1"):
    """What the simulated network carries for this instance: (start, end, gbps)."""
    _, iv = net._ours[instance_id]
    return iv.start, iv.end, iv.gbps


def assert_unchanged_t1_2(net, ctx):
    """q1/T1/2 still 12:00–13:06:40 @ 100, in the ledger, in SENSE and in the reservation."""
    assert own_on_main(ctx, 12) == [100, 100, 100] and own_on_main(ctx, 13, 30) == [0, 0, 0]
    assert in_sense(net) == (t(12), t(13, 6) + timedelta(seconds=40), 100)
    assert ctx.reservations["rsv-1"].items[0].placement.gbps == 100


# ── success ───────────────────────────────────────────────────────────────

def test_modify_a_reserved_offer(net, ctx):
    reserve(ctx, "q1/T1/2")
    resp = modify(ctx, "q1/T1/2", t(12), t(14), 50)["response"]
    assert resp == ModifyAck(reserve_id="rsv-1", offer_id="q1/T1/2",
                             rate_profile=[RateSegment(start=t(12), end=t(14), gbps=50)])
    assert own_on_main(ctx, 12) == [50, 50, 50] and own_on_main(ctx, 13, 30) == [50, 50, 50]
    assert in_sense(net) == (t(12), t(14), 50)
    item = ctx.reservations["rsv-1"].items[0]
    assert (item.placement.end, item.intent.capacity_mbps, item.intent.end) == (t(14), 50_000, t(14))
    assert ctx.sense.state("si-1").state == "reserved" and item.vlan == 3001


def test_grows_into_what_it_already_holds(ctx):
    """100 Gbps from 12:00 to 14:00: the 12:00–13:06:40 part is already ours, so it is not counted twice."""
    reserve(ctx, "q1/T1/2")
    assert isinstance(modify(ctx, "q1/T1/2", t(12), t(14), 100)["response"], ModifyAck)
    assert own_on_main(ctx, 13, 30) == [100, 100, 100]


def test_modify_a_committed_offer_updates_its_commitment(net, ctx):
    reserve(ctx, "q1/T1/2")
    c = commit(ctx)["response"].commitments[0]
    resp = modify(ctx, "q1/T1/2", t(12), t(14), 50)["response"]
    assert resp.commitment == c.model_copy(update={"rate_profile": [RateSegment(start=t(12), end=t(14), gbps=50)]})
    assert ctx.commitments[c.commitment_id] == resp.commitment
    assert ctx.sense.state("si-1").state == "committed"
    assert ctx.ledger.booking("rsv-1/q1/T1/2").state == "confirmed"


def test_commit_after_modify_uses_the_new_profile(ctx):
    reserve(ctx, "q1/T1/2")
    modify(ctx, "q1/T1/2", t(12), t(14), 50)
    resp = commit(ctx)["response"]
    assert isinstance(resp, CommitAck) and resp.commitments[0].rate_profile[0].end == t(14)


def test_started_offer_keeps_its_start(ctx):
    """q1/T1/1 started at 09:00: at 09:30 its end can change, its start cannot."""
    reserve(ctx, "q1/T1/1", ttl_seconds=3600)
    resp = modify(ctx, "q1/T1/1", t(9, 30), t(12), 40, now=t(9, 30))["response"]
    assert resp.code == "invalid_request" and "cannot move" in resp.detail
    assert isinstance(modify(ctx, "q1/T1/1", t(9), t(12), 40, now=t(9, 30))["response"], ModifyAck)


# ── rejected, nothing changes ─────────────────────────────────────────────

@pytest.mark.parametrize("over, code", [
    ({"reserve_id": "rsv-9"}, "not_found"),
    ({"offer_id": "q1/T1/1"}, "not_found"),                                 # quoted, but not in rsv-1
    ({"now": t(9, 1)}, "expired"),                                          # rsv-1 expires at 09:01
    ({"start": t(8), "end": t(9)}, "invalid_request"),                      # already past
    ({"start": t(8, 45)}, "invalid_request"),                               # starts in the past
    ({"end": t(10, day=21)}, "invalid_request"),                            # beyond the 24 h horizon
])
def test_invalid_modify_changes_nothing(net, ctx, over, code):
    reserve(ctx, "q1/T1/2")
    args = {"offer_id": "q1/T1/2", "start": t(12), "end": t(14), "gbps": 50, **over}
    assert modify(ctx, args.pop("offer_id"), args.pop("start"), args.pop("end"), args.pop("gbps"),
                  **args)["response"].code == code
    assert_unchanged_t1_2(net, ctx)


def test_released_offer_cannot_be_modified(ctx):
    reserve(ctx, "q1/T1/2")
    release(ctx)
    assert modify(ctx, "q1/T1/2", t(12), t(14), 50)["response"].code == "conflict"


def test_one_segment_only(net, ctx):
    reserve(ctx, "q1/T1/2")
    raw = ModifyRequest(request_id="m1", reserve_id="rsv-1", offer_id="q1/T1/2",
                        rate_profile=[RateSegment(start=t(12), end=t(13), gbps=100),
                                      RateSegment(start=t(13), end=t(14), gbps=50)]).model_dump()
    resp = build_modify_graph().invoke({"raw": raw, "now": t(9)}, context=ctx)["response"]
    assert resp.code == "invalid_request" and "single segment" in resp.detail
    assert_unchanged_t1_2(net, ctx)


def test_not_enough_capacity(net, ctx):
    """q1/T1/1 already takes the 40 Gbps L2 has left before 12:00; 60 does not fit."""
    reserve(ctx, "q1/T1/1")
    resp = modify(ctx, "q1/T1/1", t(9), t(11), 60)["response"]
    assert resp.code == "conflict" and "background_traffic" in resp.detail
    assert own_on_main(ctx, 9) == [40, 40, 40] and in_sense(net)[2] == 40


# ── SENSE refuses: the ledger is put back ─────────────────────────────────

def test_sense_refusal_restores_the_ledger(net, ctx):
    """Background traffic appears on L2 13:00–14:00; at 09:01 the samples are still fresh, so only SENSE
    sees it and refuses 100 Gbps until 14:00."""
    reserve(ctx, "q1/T1/2", ttl_seconds=600)
    net.add_background(L2, t(13), t(14), 30)
    out = build_modify_graph().invoke({"raw": ModifyRequest(
        request_id="m1", reserve_id="rsv-1", offer_id="q1/T1/2",
        rate_profile=[RateSegment(start=t(12), end=t(14), gbps=100)]).model_dump(), "now": t(9, 1)}, context=ctx)
    assert out["refreshed"] == []
    assert out["response"].code == "sense_failure" and "old profile stays" in out["response"].detail
    assert_unchanged_t1_2(net, ctx)


def test_injected_sense_failure(net, ctx):
    reserve(ctx, "q1/T1/2")
    ctx.sense.fail_next("modify")
    assert modify(ctx, "q1/T1/2", t(12), t(14), 50)["response"].code == "sense_failure"
    assert_unchanged_t1_2(net, ctx)


# ── ledger.replace ────────────────────────────────────────────────────────

def test_ledger_replace_is_atomic_and_keeps_the_state(ctx):
    profile = [RateSegment(start=t(12), end=t(12, 15), gbps=100)]
    ctx.ledger.pending("b", MAIN, profile)
    ctx.ledger.confirm("b")
    with pytest.raises(InsufficientCapacity):
        ctx.ledger.replace("b", [RateSegment(start=t(9), end=t(12, 15), gbps=100)])   # 09:00 has 40 left
    assert own_on_main(ctx, 12) == [100, 100, 100] and own_on_main(ctx, 9) == [0, 0, 0]
    ctx.ledger.replace("b", [RateSegment(start=t(12), end=t(12, 30), gbps=80)])
    assert own_on_main(ctx, 12, 15) == [80, 80, 80]
    assert ctx.ledger.booking("b").state == "confirmed"


# ── through graph A ───────────────────────────────────────────────────────

def test_modify_through_protocol_graph(net):
    ctx, graph = make_ctx(net), build_protocol_graph()

    def send(verb, msg):
        return graph.invoke({"verb": verb, "raw": msg.model_dump(), "now": t(9)}, context=ctx)

    send("quote", QuoteRequest(quote_id="q1", bundle=[tr()], mode="all_or_nothing"))
    send("reserve", ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T1/2"]))
    out = send("modify", ModifyRequest(request_id="m1", reserve_id="rsv-1", offer_id="q1/T1/2",
                                       rate_profile=[RateSegment(start=t(12), end=t(14), gbps=50)]))
    assert isinstance(out["response"], ModifyAck)
    assert in_sense(net) == (t(12), t(14), 50)
