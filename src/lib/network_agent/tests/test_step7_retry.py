"""Failed repairs are retried on changed inputs or timeout; identical reports are independently suppressed."""

from datetime import timedelta

import pytest

from ..src.models.config import load_config
from ..src.models.schemas import RateSegment, TelemetryAlert
from .helpers import (ALT, CFG, L2, L2_BACK, L4, TICK, follow_reroutes, make_committed_ctx, make_net,
                      modify, release, reports, runtime, t)

TB = 10**12


@pytest.fixture
def blocked():
    """MAIN is down until the deadline; a separate pending hold fills ALT until then."""
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(15))
    ctx.ledger.pending("other-hold", (L4,), [RateSegment(start=t(10), end=t(15), gbps=40)])
    return net, ctx


def first_failure(ctx):
    out = runtime(ctx, TICK, t(10))
    assert reports(out) == [("cmt-1", "link_down", "unresolved", None)]
    assert "reroute" in out["plans"][0].steps
    return ctx.failed_repairs["cmt-1"]


def test_released_capacity_retries_before_timeout_and_reroutes(blocked):
    net, ctx = blocked
    failed = first_failure(ctx)
    original = ctx.commitments["cmt-1"]
    ctx.ledger.free("other-hold")
    now = t(10, 1)
    assert now < failed.retry_after
    out = runtime(ctx, TICK, now)
    assert out["assessments"][0].committed.commitment == original
    assert out["assessments"][0].remaining_bytes == failed.conditions.remaining_bytes
    assert reports(out) == [("cmt-1", "link_down", "repaired", "reroute")]
    assert ctx.reservations["rsv-1"].held[0].placement.path == ALT
    assert not ctx.failed_repairs and not ctx.reported_unresolved
    follow_reroutes(net, out, now)
    report = out["reports"]["link_down"][0]
    assert net.flow_trace(report.commitment.circuit_id, t(23)).finished_at == report.predicted_finish_p95
    assert report.predicted_finish_p95 <= report.latest_finish


def test_stale_alternate_path_is_refreshed_before_deduplication(blocked):
    net, ctx = blocked
    ctx.ledger.free("other-hold")
    net.add_background(L4, t(10), t(15), 40)
    failed = first_failure(ctx)
    # The telemetry source learns that this background traffic ended early.
    net._background[L4].clear()
    out = runtime(ctx, TICK, t(10, 5))
    assert t(10, 5) < failed.retry_after and L4 in out["refreshed"]
    assert reports(out) == [("cmt-1", "link_down", "repaired", "reroute")]


def test_new_timestamps_and_unrelated_bookings_do_not_trigger_retry(blocked):
    _, ctx = blocked
    failed = first_failure(ctx)
    slot = ctx.ledger.slots_covering(t(10), t(10, 1))[0]
    before = ctx.ledger.observed(L4, slot).at
    ctx.ledger.pending("reverse-direction", (L2_BACK,), [RateSegment(start=t(10), end=t(15), gbps=10)])
    out = runtime(ctx, TICK, t(10, 5))
    assert ctx.ledger.observed(L4, slot).at > before
    assert out["retry_deferred"] == ["cmt-1"]
    assert "plans" not in out and not reports(out)
    assert ctx.failed_repairs["cmt-1"] == failed


def test_timeout_retries_but_does_not_repeat_identical_report(blocked):
    _, ctx = blocked
    ctx.cfg = load_config({**CFG, "repair_retry_seconds": 60})
    first = first_failure(ctx)
    assert first.retry_after == t(10, 1)
    early = runtime(ctx, TICK, t(10) + timedelta(seconds=59))
    assert early["retry_deferred"] == ["cmt-1"]
    out = runtime(ctx, TICK, t(10, 1))
    assert out["retry_deferred"] == [] and out["repair_results"][0].outcome == "unresolved"
    assert out["reports"] == {}
    next_failure = ctx.failed_repairs["cmt-1"]
    assert next_failure.conditions == first.conditions
    assert next_failure.retry_after == t(10, 2)
    assert runtime(ctx, TICK, t(10, 1) + timedelta(seconds=1))["retry_deferred"] == ["cmt-1"]


def test_link_alert_and_tick_share_commitment_retry_history(blocked):
    _, ctx = blocked
    failed = first_failure(ctx)
    alert = TelemetryAlert(alert_id="new-delivery", kind="link_down", link_id=L2,
                           start=t(9, 30), end=t(15), observed_at=t(10, 1), source="mock")
    out = runtime(ctx, alert, t(10, 1))
    assert L2 in out["refreshed"]
    assert out["retry_deferred"] == ["cmt-1"] and "repair_results" not in out
    assert ctx.failed_repairs["cmt-1"] == failed


def test_remaining_bytes_change_retries_before_timeout(blocked):
    net, ctx = blocked
    # Restore MAIN at 10:00, but leave too little capacity to finish before 15:00.
    for link in (L2, L2_BACK):
        net._outages[link].clear()
    net.add_outage("L2", t(9, 30), t(10))
    net.add_background(L2, t(10), t(15), 35)
    first = first_failure(ctx)
    out = runtime(ctx, TICK, t(10, 1))
    assert out["assessments"][0].remaining_bytes < first.conditions.remaining_bytes
    assert out["retry_deferred"] == [] and "repair_results" in out


def test_release_clears_history_even_without_a_deviation(blocked):
    _, ctx = blocked
    first_failure(ctx)
    release(ctx, now=t(10, 1))
    out = runtime(ctx, TICK, t(10, 2))
    assert not out["deviations"]
    assert not ctx.failed_repairs and not ctx.reported_unresolved


def test_modified_commitment_gets_a_new_attempt(blocked):
    _, ctx = blocked
    first = first_failure(ctx)
    # Shrink the existing reservation: the failure is still present, but the contract changed.
    response = modify(ctx, "q1/T1/1", t(9), t(11, 30), 40, now=t(10, 1))["response"]
    assert response.commitment != first.conditions.commitment
    out = runtime(ctx, TICK, t(10, 2))
    assert out["retry_deferred"] == [] and "repair_results" in out
    assert reports(out) == [("cmt-1", "link_down", "unresolved", None)]


def test_recovery_clears_history_then_a_new_outage_is_not_suppressed(blocked):
    net, ctx = blocked
    # No transfer has started; only future link damage triggers detection.
    net._flows.clear()
    first_failure(ctx)
    for link in (L2, L2_BACK):
        net._outages[link].clear()
    recovered = TelemetryAlert(alert_id="up", kind="link_up", link_id=L2,
                               start=t(10, 1), observed_at=t(10, 1), source="mock")
    assert not runtime(ctx, recovered, t(10, 1))["deviations"]
    assert not ctx.failed_repairs and not ctx.reported_unresolved
    net.add_outage("L2", t(9, 30), t(15))
    down = TelemetryAlert(alert_id="down-again", kind="link_down", link_id=L2,
                          start=t(9, 30), observed_at=t(10, 2), source="mock")
    assert reports(runtime(ctx, down, t(10, 2))) == [("cmt-1", "link_down", "unresolved", None)]
