"""Step 5a: the reserve branch of graph A (``hold`` in the slides).

Every test starts from the slide-7 network quoted at 09:00 with two transfers (helpers.make_quoted_ctx;
all offers on the main path L1 → L2 → L3):

    q1/T1/1  09:00 @  40 Gbps → 11:46:40      q1/T2/1  09:00 @  40 Gbps → 09:03:20
    q1/T1/2  12:00 @ 100 Gbps → 13:06:40      q1/T2/2  12:00 @ 100 Gbps → 12:01:20
    q1/T1/3  09:00 @  20 Gbps → 14:33:20      q1/T2/3  09:00 @  10 Gbps → 09:13:20
"""

from datetime import timedelta

import pytest

from ..graphs.reserve import build_reserve_graph
from ..ledger import InsufficientCapacity
from ..schemas import RateSegment, ReserveAck, Terminal
from .helpers import DST, L2, MAIN, SRC, make_net, make_quoted_ctx, reserve, t


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    return make_quoted_ctx(net)


def assert_untouched(net, ctx):
    """A failed reserve leaves no trace: no reservation, no booking, nothing held in SENSE."""
    assert ctx.reservations == {}
    assert all(ctx.ledger.own(link, i) == 0 for link in MAIN for i in range(ctx.ledger.n_slots))
    assert net._ours == {}


# ── success ───────────────────────────────────────────────────────────────

def test_reserve_debits_ledger_and_holds_in_sense(net, ctx):
    resp = reserve(ctx, "q1/T1/1")["response"]
    assert resp == ReserveAck(reserve_id="rsv-1", offer_ids=["q1/T1/1"], expires_at=t(9, 1))  # TTL 60 s from the config

    # ledger: 40 Gbps pending on every hop of the main path; L2 had exactly 40 left, so the next quote sees 0
    assert ctx.ledger.booking("rsv-1/q1/T1/1").state == "pending"
    assert [ctx.ledger.own(link, 0) for link in MAIN] == [40, 40, 40]
    assert ctx.ledger.available(L2, 0) == 0

    # SENSE: one instance in state reserved, on the same path
    item = ctx.reservations["rsv-1"].items[0]
    assert ctx.sense.state(item.instance_id).state == "reserved"
    assert item.vlan == 3001
    assert net._ours[item.instance_id][0] == MAIN


def test_intent_follows_the_offer(ctx):
    reserve(ctx, "q1/T1/2")
    intent = ctx.reservations["rsv-1"].items[0].intent
    assert intent.terminals == [Terminal(uri=SRC), Terminal(uri=DST)]
    assert intent.path_inclusion == list(MAIN)
    assert (intent.capacity_mbps, intent.qos_class) == (100_000, "guaranteedCapped")
    assert (intent.start, intent.end) == (t(12), t(13, 6) + timedelta(seconds=40))
    assert intent.alias == "rsv-1/q1/T1/2"


def test_group_is_reserved_together(ctx):
    resp = reserve(ctx, "q1/T1/2", "q1/T2/1")["response"]
    assert resp.offer_ids == ["q1/T1/2", "q1/T2/1"]
    items = ctx.reservations["rsv-1"].items
    assert [i.vlan for i in items] == [3001, 3002]
    assert len({i.instance_id for i in items}) == 2           # one SENSE instance per offer


def test_ttl_from_request_overrides_config(ctx):
    assert reserve(ctx, "q1/T1/1", ttl_seconds=600)["response"].expires_at == t(9, 10)


# ── rejected before anything is written ───────────────────────────────────

@pytest.mark.parametrize("offer_ids, over, code", [
    (["q1/T9/1"], {}, "not_found"),                            # never quoted
    (["q1/T1/1"], {"quote_id": "q2"}, "invalid_request"),      # offer belongs to another quote
    (["q1/T1/1", "q1/T1/2"], {}, "invalid_request"),           # two offers for the same transfer
    (["q1/T1/1"], {"now": t(12)}, "expired"),                  # 09:00–11:46:40 is already over
])
def test_invalid_reserve_changes_nothing(net, ctx, offer_ids, over, code):
    resp = reserve(ctx, *offer_ids, **over)["response"]
    assert (resp.request_id, resp.code) == ("r1", code)
    assert_untouched(net, ctx)


def test_malformed_request(net, ctx):
    raw = {"request_id": "r9", "quote_id": "q1", "offer_ids": []}
    resp = build_reserve_graph().invoke({"raw": raw, "now": t(9)}, context=ctx)["response"]
    assert (resp.request_id, resp.code) == ("r9", "invalid_request")
    assert_untouched(net, ctx)


def test_offer_cannot_be_reserved_twice(ctx):
    reserve(ctx, "q1/T1/2")
    resp = reserve(ctx, "q1/T1/2")["response"]
    assert resp.code == "conflict"
    assert list(ctx.reservations) == ["rsv-1"]


# ── the network changed after the quote ───────────────────────────────────

def test_recheck_catches_capacity_lost_since_quote(net, ctx):
    """Others take 30 more Gbps on L2 after the quote. At 09:10 the quote-time samples (valid 5 min) are stale,
    recheck refreshes them, and the debit is refused before SENSE is ever called."""
    net.add_background(L2, t(9), t(12), 30)                    # 90 of 100 used → 10 left, offer needs 40
    out = reserve(ctx, "q1/T1/1", now=t(9, 10))
    assert L2 in out["refreshed"]
    assert out["response"].code == "conflict"
    assert "L2:esnet-atl>esnet-chi" in out["response"].detail
    assert_untouched(net, ctx)


def test_sense_refusal_rolls_back_the_whole_group(net, ctx):
    """Same kind of change, but at 09:01 the samples are still fresh, so the ledger does not know yet.
    SENSE accepts the first offer and refuses the second; the first must be cancelled and both bookings returned."""
    net.add_background(L2, t(12), t(13), 30)                   # 12:00–13:00 only 70 left; q1/T1/2 needs 100
    out = reserve(ctx, "q1/T2/1", "q1/T1/2", now=t(9, 1))
    assert out["refreshed"] == []
    assert out["response"].code == "sense_failure"
    assert ctx.sense.state("si-1").state == "cancelled"        # q1/T2/1 had been propagated
    assert_untouched(net, ctx)


def test_failed_cancel_is_reported(net, ctx):
    """If cancelling during rollback also fails, the error says what is left held in SENSE. That instance
    becomes an orphan and keeps its booking (step 5b: the sweep cancels it); the other booking is returned."""
    net.add_background(L2, t(12), t(13), 30)
    ctx.sense.fail_next("cancel")
    resp = reserve(ctx, "q1/T2/1", "q1/T1/2", now=t(9, 1))["response"]
    assert resp.code == "sense_failure" and "cancel also failed" in resp.detail and "si-1" in resp.detail
    assert ctx.sense.state("si-1").state == "reserved"
    assert ctx.reservations == {}
    assert ctx.orphans == {"si-1": "rsv-1/q1/T2/1"}
    assert ctx.ledger.booking("rsv-1/q1/T2/1").state == "pending"
    noon = ctx.ledger.slots_covering(t(12), t(12, 1))[0]
    assert [ctx.ledger.own(link, noon) for link in MAIN] == [0, 0, 0]          # q1/T1/2 was never propagated


# ── ledger: debiting a group ──────────────────────────────────────────────

def test_pending_group_is_all_or_nothing(ctx):
    """Two bookings that each fit alone but not together (L2 has 40 left at 09:00): neither is written."""
    profile = [RateSegment(start=t(9), end=t(9, 15), gbps=30)]
    with pytest.raises(InsufficientCapacity):
        ctx.ledger.pending_group([("a", MAIN, profile), ("b", MAIN, profile)])
    assert ctx.ledger.own(L2, 0) == 0
