"""Step 5b: resent requests through graph A (dedupe_request / remember_response).

A scheduling agent that lost a reply sends the same request again; every verb must then give the same
reply without doing the work twice.
"""

import pytest

from ..graphs.protocol import build_protocol_graph
from ..schemas import CommitAck, CommitRequest, ModifyRequest, QuoteResponse, RateSegment, ReleaseRequest
from .helpers import C1, L2, R1, make_ctx, make_net, quote_t1_t2, t


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def agent(net):
    ctx, graph = make_ctx(net), build_protocol_graph()

    def send(verb, msg, now=t(9)):
        raw = msg.model_dump() if hasattr(msg, "model_dump") else msg
        return graph.invoke({"verb": verb, "raw": raw, "now": now}, context=ctx)

    send("quote", quote_t1_t2())
    return ctx, send


# ── the same request twice: the same reply, nothing runs again ────────────

def test_resent_reserve(net, agent):
    ctx, send = agent
    first = send("reserve", R1)
    again = send("reserve", R1)
    assert again["replayed"] and again["response"] == first["response"]
    assert list(ctx.reservations) == ["rsv-1"] and len(net._ours) == 2


def test_resent_commit_keeps_the_binding(agent):
    ctx, send = agent
    send("reserve", R1)
    first = send("commit", C1)["response"]
    again = send("commit", C1)["response"]
    assert isinstance(again, CommitAck) and again == first
    assert [c.binding.vlan for c in again.commitments] == [3001, 3002]
    assert len(ctx.commitments) == 2


def test_resent_quote_gives_the_same_offers(net, agent):
    """Even after the network changed, a resent q1 gets the original offers, and offer_book keeps them."""
    ctx, send = agent
    book = dict(ctx.offer_book)
    net.add_background(L2, t(12), t(13), 30)
    again = send("quote", quote_t1_t2(), now=t(9, 10))
    assert again["replayed"] and isinstance(again["response"], QuoteResponse)
    assert ctx.offer_book == book


def test_resent_release_and_modify(agent):
    ctx, send = agent
    send("reserve", R1)
    m1 = ModifyRequest(request_id="m1", reserve_id="rsv-1", offer_id="q1/T1/2",
                       rate_profile=[RateSegment(start=t(12), end=t(14), gbps=50)])
    x1 = ReleaseRequest(request_id="x1", reserve_id="rsv-1", offer_ids=["q1/T2/1"])
    for verb, msg in [("modify", m1), ("release", x1)]:
        first = send(verb, msg)
        again = send(verb, msg)
        assert again["replayed"] and again["response"] == first["response"]
    assert [i.offer_id for i in ctx.reservations["rsv-1"].held] == ["q1/T1/2"]


def test_replay_runs_nothing(agent):
    """A replay skips the sweep too: rsv-1 expired at 09:01, yet the resent r1 only gets its old ack."""
    ctx, send = agent
    send("reserve", R1)
    again = send("reserve", R1, now=t(9, 2))
    assert again["replayed"] and "swept" not in again
    assert ctx.reservations["rsv-1"].state == "reserved"


# ── what is not replayed ──────────────────────────────────────────────────

def test_same_id_different_request_is_refused(agent):
    ctx, send = agent
    send("reserve", R1)
    resp = send("reserve", R1.model_copy(update={"offer_ids": ["q1/T1/1"]}))["response"]
    assert (resp.request_id, resp.code) == ("r1", "invalid_request")
    assert "different request" in resp.detail
    assert list(ctx.reservations) == ["rsv-1"]


def test_failure_is_not_cached_so_a_resend_retries(agent):
    ctx, send = agent
    send("reserve", R1)
    ctx.sense.fail_next("commit")
    assert send("commit", C1)["response"].code == "sense_failure"
    again = send("commit", C1)
    assert "replayed" not in again and isinstance(again["response"], CommitAck)


def test_ids_are_per_verb(agent):
    """request_id "r1" for a commit is not the reserve r1."""
    _, send = agent
    send("reserve", R1)
    out = send("commit", CommitRequest(request_id="r1", reserve_id="rsv-1"))
    assert "replayed" not in out and isinstance(out["response"], CommitAck)


def test_malformed_request_is_answered_by_the_branch(agent):
    ctx, send = agent
    raw = {"request_id": "r9", "quote_id": "q1", "offer_ids": []}
    for _ in range(2):
        out = send("reserve", raw)
        assert "replayed" not in out and out["response"].code == "invalid_request"
    assert ctx.answered.keys() == {("quote", "q1")}
