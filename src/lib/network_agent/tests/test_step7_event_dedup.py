"""Entry deduplication stops duplicate delivery work, independently of commitment repair retries."""

from datetime import timedelta

import pytest

from ..src.models.schemas import TelemetryAlert
from .helpers import L2, L3, TICK, make_committed_ctx, make_net, runtime, t, visited


def alert(**changes):
    fields = dict(alert_id="a1", kind="link_capacity_below", link_id=L2, start=t(9), end=t(12),
                  measured_gbps=40, observed_at=t(10), source="mock")
    return TelemetryAlert(**(fields | changes))


@pytest.fixture
def ctx():
    return make_committed_ctx(make_net())


def test_duplicate_stops_before_any_flow_or_telemetry_read(ctx, monkeypatch):
    first = runtime(ctx, alert(), t(10))
    assert not first["duplicate_event"] and L2 in first["refreshed"]      # the forecast re-measured L2

    def unexpected_read(*args, **kwargs):
        pytest.fail("duplicate must stop before external reads")

    monkeypatch.setattr(ctx.telemetry, "link_samples", unexpected_read)
    monkeypatch.setattr(ctx.flows, "progress", unexpected_read)
    # Same content as JSON, a new delivery id and a later observation timestamp.
    resent = alert(alert_id="a2", observed_at=t(10) + timedelta(seconds=1)).model_dump(mode="json")
    assert visited(ctx, resent, t(10) + timedelta(seconds=1)) == ["deduplicate_event"]
    out = runtime(ctx, resent, t(10) + timedelta(seconds=2))
    assert out["duplicate_event"] and "checked" not in out and "reports" not in out


@pytest.mark.parametrize("change", [
    {"source": "another-source"},
    {"kind": "link_down"},
    {"link_id": L3},
    {"start": t(9, 1)},
    {"end": t(12, 1)},
    {"end": None},
    {"measured_gbps": 30},
])
def test_changed_condition_is_processed_even_with_same_alert_id(ctx, change):
    runtime(ctx, alert(), t(10))
    out = runtime(ctx, alert(**change), t(10) + timedelta(seconds=1))
    assert not out["duplicate_event"] and "checked" in out


def test_different_flows_are_not_duplicates(ctx):
    fields = dict(alert_id="f1", kind="flow_stalled", flow_id="si-1", start=t(9, 59), end=t(10),
                  observed_at=t(10), source="mock")
    first = TelemetryAlert(**fields)
    runtime(ctx, first, t(10))
    second = TelemetryAlert(**(fields | {"flow_id": "si-other"}))
    assert not runtime(ctx, second, t(10))["duplicate_event"]
    assert runtime(ctx, first, t(10))["duplicate_event"]


def test_ticks_and_invalid_events_always_pass(ctx):
    runtime(ctx, alert(), t(10))
    for event in (TICK, TICK, {"kind": "unsupported"}, {"kind": "unsupported"}):
        out = runtime(ctx, event, t(10))
        assert not out["duplicate_event"] and out["checked"] == ["cmt-1"]
        if event != TICK:
            assert "invalid_event" in out
    assert len(ctx.processed_alerts) == 1


def test_expiry_is_not_extended_by_duplicates_and_tick_prunes_cache(ctx):
    runtime(ctx, alert(), t(10))
    expires_at = t(10) + timedelta(seconds=ctx.cfg.event_dedup_seconds)
    assert runtime(ctx, alert(), expires_at - timedelta(seconds=1))["duplicate_event"]
    assert list(ctx.processed_alerts.values()) == [expires_at]
    out = runtime(ctx, alert(), expires_at)
    assert not out["duplicate_event"] and "checked" in out
    runtime(ctx, TICK, expires_at + timedelta(seconds=ctx.cfg.event_dedup_seconds))
    assert not ctx.processed_alerts


def test_failed_processing_does_not_poison_duplicate_cache(ctx, monkeypatch):
    read = ctx.telemetry.link_samples

    def unavailable(*args, **kwargs):
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(ctx.telemetry, "link_samples", unavailable)
    with pytest.raises(RuntimeError, match="telemetry unavailable"):
        runtime(ctx, alert(), t(10))
    assert not ctx.processed_alerts
    monkeypatch.setattr(ctx.telemetry, "link_samples", read)
    assert not runtime(ctx, alert(), t(10))["duplicate_event"]
    assert runtime(ctx, alert(), t(10))["duplicate_event"]


def test_successful_repair_is_cached_and_tick_still_checks(ctx):
    net = ctx.telemetry.network
    net.start_flow("si-1", t(9), 50 * 10**12)
    net.add_outage("L2", t(10), t(10, 15), planned=False)
    event = alert(kind="link_down", start=t(10), end=None)
    first = runtime(ctx, event, t(10))
    # unplanned: forecast down until 11:00 (p50) / 13:00 (p95), past the reservation's end: reroute
    assert first["reports"]["link_down"][0].action == "reroute"
    assert runtime(ctx, event, t(10))["duplicate_event"]
    out = runtime(ctx, TICK, t(10))
    assert not out["duplicate_event"] and out["checked"] == ["cmt-1"]      # a tick is never deduplicated
