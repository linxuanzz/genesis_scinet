"""Step 1: message schemas. Valid messages can be built and survive a JSON round trip; invalid ones are rejected at the door.

Examples follow slide 7: T1 = 50 TB, window 09:00–15:00; offer a2 = 100 Gbps from 12:00, done at 13:07.
"""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from ..schemas import (
    CommitAck, Commitment, EndpointBinding, Offer, QuoteRequest, QuoteResponse,
    RateSegment, RejectReason, ReserveRequest, TimeWindow, TransferQuote, TransferRequest,
)
from .helpers import DST, SRC, t


def t1(**over):
    base = dict(id="T1", workflow_id="WF-1", priority=1, src=SRC, dst=DST,
                bytes=50 * 10**12, is_estimate=False, divisible=False,
                window=TimeWindow(earliest_start=t(9), latest_finish=t(15)))
    return TransferRequest(**(base | over))


def a2(**over):
    base = dict(offer_id="a2", transfer_id="T1",
                rate_profile=[RateSegment(start=t(12), end=t(13, 7), gbps=100)],
                predicted_finish_p50=t(13, 7), predicted_finish_p95=t(13, 20))
    return Offer(**(base | over))


# ── valid messages ────────────────────────────────────────────────────────

def test_valid_quote_roundtrip_json():
    q = QuoteRequest(quote_id="q1", bundle=[t1(), t1(id="T2")], mode="all_or_nothing")
    assert QuoteRequest.model_validate_json(q.model_dump_json()) == q


def test_offer_start_is_first_segment():
    assert a2().start == t(12)


def test_commit_ack_roundtrip_json():
    b = EndpointBinding(transfer_id="T1", src_uri="urn:anl", dst_uri="urn:ornl", vlan=3001, interface="eth1")
    c = Commitment(commitment_id="c1", transfer_id="T1", workflow_id="WF-1", circuit_id="C1",
                   rate_profile=a2().rate_profile, binding=b)
    ack = CommitAck(reserve_id="r1", commitments=[c])
    assert CommitAck.model_validate_json(ack.model_dump_json()) == ack


def test_binding_interface_is_optional():
    """SENSE only gives the VLAN; the NIC name comes from site configuration and may be missing."""
    b = EndpointBinding(transfer_id="T1", src_uri="urn:anl", dst_uri="urn:ornl", vlan=3001)
    assert b.interface is None


# ── invalid messages are rejected ─────────────────────────────────────────

@pytest.mark.parametrize("make", [
    lambda: TimeWindow(earliest_start=t(15), latest_finish=t(9)),                     # window reversed
    lambda: TimeWindow(earliest_start=datetime(2026, 10, 20, 9), latest_finish=t(15)),  # no timezone
    lambda: t1(bytes=0),                                                              # bytes not positive
    lambda: t1(dst=SRC),                                                              # src == dst
    lambda: t1(color="red"),                                                          # unknown field
    lambda: QuoteRequest(quote_id="q", bundle=[], mode="best_subset"),                # empty bundle
    lambda: QuoteRequest(quote_id="q", bundle=[t1(), t1()], mode="best_subset"),      # duplicate transfer id
    lambda: QuoteRequest(quote_id="q", bundle=[t1()], mode="some"),                   # invalid mode
    lambda: RateSegment(start=t(12), end=t(12), gbps=10),                             # empty time range
    lambda: RateSegment(start=t(12), end=t(13), gbps=0),                              # rate not positive
    lambda: a2(rate_profile=[RateSegment(start=t(12), end=t(13), gbps=10),
                             RateSegment(start=t(12, 30), end=t(14), gbps=10)]),      # overlapping segments
    lambda: a2(predicted_finish_p95=t(13)),                                           # p95 < p50
    lambda: a2(predicted_finish_p50=t(11), predicted_finish_p95=t(11)),               # finishes before it starts
    lambda: ReserveRequest(request_id="r", quote_id="q", offer_ids=["a2", "a2"]),     # duplicate offer
    lambda: EndpointBinding(transfer_id="T1", src_uri="u", dst_uri="v", vlan=5000, interface="e"),
])
def test_rejected(make):
    with pytest.raises(ValidationError):
        make()


def test_frozen():
    with pytest.raises(ValidationError):
        t1().bytes = 1


# ── consistency of quote results ──────────────────────────────────────────

def test_transfer_quote_consistency():
    no_cap = RejectReason(cause="no_capacity", detail="window full")
    TransferQuote(transfer_id="T1", status="feasible", offers=[a2()])
    TransferQuote(transfer_id="T1", status="infeasible", reason=no_cap)
    with pytest.raises(ValidationError):
        TransferQuote(transfer_id="T1", status="feasible")                    # feasible but no offers
    with pytest.raises(ValidationError):
        TransferQuote(transfer_id="T1", status="infeasible")                  # infeasible but no reason
    with pytest.raises(ValidationError):
        TransferQuote(transfer_id="T2", status="feasible", offers=[a2()])     # offer belongs to another transfer


def test_admissible_depends_on_mode():
    ok = TransferQuote(transfer_id="T1", status="feasible", offers=[a2()])
    bad = TransferQuote(transfer_id="T2", status="unreachable",
                        reason=RejectReason(cause="no_path", detail="no route"))
    assert not QuoteResponse(quote_id="q", mode="all_or_nothing", results=[ok, bad]).admissible
    assert QuoteResponse(quote_id="q", mode="best_subset", results=[ok, bad]).admissible
    assert not QuoteResponse(quote_id="q", mode="best_subset", results=[bad]).admissible


def test_slide7_arithmetic():
    """Slide 7 time arithmetic: 50 TB at 100 Gbps takes 4000 s (≈ 1 h 07 min)."""
    seconds = t1().bytes * 8 / (100 * 10**9)
    assert t(12) + timedelta(seconds=seconds) == t(13, 6) + timedelta(seconds=40)
