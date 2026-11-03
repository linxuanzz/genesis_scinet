"""Step 5a: the commit branch of graph A, and graph A as a whole (route_verb + three branches).

Starts from the same queried agent as the reserve tests (helpers.make_queried_ctx); TTL is 60 s, so a
reservation made at 09:00 must be committed before 09:01.
"""

from datetime import timedelta

import pytest

from ..graphs.protocol import build_protocol_graph
from ..schemas import (
    CommitAck, CommitRequest, EndpointBinding, ErrorResponse, QueryRequest, QueryResponse, RateSegment, ReserveAck,
    ReserveRequest,
)
from ..sense import SenseError
from .helpers import DST, MAIN, SRC, commit, make_ctx, make_net, make_queried_ctx, reserve, t, tr


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    return make_queried_ctx(net)


# ── success ───────────────────────────────────────────────────────────────

def test_commit_turns_reservation_into_commitment(ctx):
    reserve(ctx, "q1/T1/2")                                    # 12:00 @ 100 Gbps → 13:06:40
    resp = commit(ctx)["response"]
    assert isinstance(resp, CommitAck) and resp.reserve_id == "rsv-1"
    [c] = resp.commitments
    assert (c.transfer_id, c.workflow_id, c.circuit_id) == ("T1", "WF-1", "si-1")
    assert c.rate_profile == [RateSegment(start=t(12), end=t(13, 6) + timedelta(seconds=40), gbps=100)]
    assert c.binding == EndpointBinding(transfer_id="T1", src_uri=SRC, dst_uri=DST, vlan=3001)  # interface: None

    # SENSE committed, ledger confirmed, reservation marked, commitment kept
    assert ctx.sense.state("si-1").state == "committed"
    assert ctx.ledger.booking("rsv-1/q1/T1/2").state == "confirmed"
    assert ctx.reservations["rsv-1"].state == "committed"
    assert ctx.commitments[c.commitment_id] == c


def test_commit_does_not_debit_again(ctx):
    """Capacity was taken at reserve; commit only changes the booking's state."""
    reserve(ctx, "q1/T1/2")
    slot = ctx.ledger.slots_covering(t(12), t(12, 15))[0]
    before = [ctx.ledger.own(link, slot) for link in MAIN]
    commit(ctx)
    assert [ctx.ledger.own(link, slot) for link in MAIN] == before == [100, 100, 100]


def test_group_commits_together(ctx):
    reserve(ctx, "q1/T1/2", "q1/T2/1")
    resp = commit(ctx)["response"]
    assert [(c.transfer_id, c.binding.vlan) for c in resp.commitments] == [("T1", 3001), ("T2", 3002)]


# ── rejected ──────────────────────────────────────────────────────────────

def test_unknown_reservation(ctx):
    resp = commit(ctx, reserve_id="rsv-9")["response"]
    assert (resp.request_id, resp.code) == ("c1", "not_found")


def test_expired_reservation(ctx):
    reserve(ctx, "q1/T1/2")                                    # expires 09:01
    resp = commit(ctx, now=t(9, 1))["response"]
    assert resp.code == "expired"
    assert ctx.ledger.booking("rsv-1/q1/T1/2").state == "pending"   # the branch alone does not reclaim; graph A's sweep does


def test_cannot_commit_twice(ctx):
    reserve(ctx, "q1/T1/2")
    commit(ctx)
    assert commit(ctx)["response"].code == "conflict"
    assert len(ctx.commitments) == 1


# ── SENSE fails: nothing is rolled back, the commit can be retried ──────────

def test_failed_commit_keeps_reservation(ctx):
    reserve(ctx, "q1/T1/2")
    ctx.sense.fail_next("commit")
    resp = commit(ctx)["response"]
    assert resp.code == "sense_failure"
    assert ctx.ledger.booking("rsv-1/q1/T1/2").state == "pending"
    assert ctx.sense.state("si-1").state == "reserved"
    assert ctx.reservations["rsv-1"].state == "reserved" and ctx.commitments == {}

    assert isinstance(commit(ctx, now=t(9, 0) + timedelta(seconds=30))["response"], CommitAck)  # retry within TTL


def test_retry_after_partial_commit(monkeypatch, ctx):
    """SENSE commits the first instance of the group and fails on the second. The retry must not commit
    si-1 again (SENSE would refuse: it is no longer reserved) but only finish si-2."""
    reserve(ctx, "q1/T1/2", "q1/T2/1")
    real, calls = ctx.sense.commit, []

    def flaky(instance_id, now):
        calls.append(instance_id)
        if len(calls) == 2:
            raise SenseError("commit", "injected")
        return real(instance_id, now)

    monkeypatch.setattr(ctx.sense, "commit", flaky)
    assert commit(ctx)["response"].code == "sense_failure"
    assert [ctx.sense.state(i).state for i in ("si-1", "si-2")] == ["committed", "reserved"]

    resp = commit(ctx)["response"]
    assert len(resp.commitments) == 2
    assert calls == ["si-1", "si-2", "si-2"]                   # si-1 was not committed twice


# ── graph A as a whole ────────────────────────────────────────────────────

def test_one_graph_query_reserve_commit(net):
    """The scheduling agent's view: three messages into the same graph, each routed by its verb."""
    ctx, graph = make_ctx(net), build_protocol_graph()

    def send(verb, msg, now=t(9)):
        return graph.invoke({"verb": verb, "raw": msg.model_dump(), "now": now}, context=ctx)

    q = send("query", QueryRequest(query_id="q1", bundle=[tr()], mode="all_or_nothing"))
    assert isinstance(q["response"], QueryResponse)
    assert set(q) == {"verb", "raw", "now", "swept", "response"}   # branch-internal fields stay inside the branch

    r = send("reserve", ReserveRequest(request_id="r1", query_id="q1", offer_ids=["q1/T1/2"]))
    assert isinstance(r["response"], ReserveAck)

    c = send("commit", CommitRequest(request_id="c1", reserve_id=r["response"].reserve_id))
    assert [x.transfer_id for x in c["response"].commitments] == ["T1"]


def test_unknown_verb(net):
    out = build_protocol_graph().invoke({"verb": "hold", "raw": {"request_id": "x1"}, "now": t(9)},
                                        context=make_ctx(net))
    assert isinstance(out["response"], ErrorResponse)
    assert (out["response"].request_id, out["response"].code) == ("x1", "invalid_request")
