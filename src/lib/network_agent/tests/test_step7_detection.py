"""Step 7 detection: which commitments deviate, in which branch, and why (link_down / congestion /
late_start / unlocated).

    flow branch, slow      throughput below the reserved rate, located on the current slot
    flow branch, overrun   remaining bytes exceed what the reservation can still carry, located since the start
    link branch            a booked slot from now on where a hop is down or squeezed

Unless a test says otherwise, the agent has committed cmt-1 = q1/T1/1 on si-1: 09:00–11:46:40 @ 40 Gbps
along MAIN (L2 has 40 left before 12:00), and the WMS starts its 50 TB at 09:00. 40 Gbps for an hour
moves 18 TB; the tolerance (CFG) is 5 %. A first progress reading has no recent rate, so it can only
overrun, not be slow.
"""

import pytest

from ..src.adapters.telemetry import MockAlerts
from ..src.models.schemas import RateSegment, Subscribe, TelemetryAlert, Tick
from ..src.runtime.detection import bytes_carried, is_short
from .helpers import L2, L3, L4, TICK, make_committed_ctx, make_net, runtime, t, visited

TB = 10**12


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    return ctx


def link_alert(kind, link_id, at, **over):
    return TelemetryAlert(alert_id="a1", kind=kind, link_id=link_id, start=at, observed_at=at, source="mock", **over)


def flow_alert(kind, flow_id, at, **over):
    return TelemetryAlert(alert_id="a2", kind=kind, flow_id=flow_id, start=at, observed_at=at, source="mock", **over)


def only(out):
    [d] = out["deviations"]
    return d


# ── flow branch ───────────────────────────────────────────────────────────

def test_on_track_ends(ctx):
    out = runtime(ctx, TICK, t(10))
    assert out["deviations"] == [] and out["checked"] == ["cmt-1"]
    assert visited(ctx, TICK, t(10)) == ["deduplicate_event", "update_forecast", "detect_deviations", "remember_event"]


def test_bytes_lost_to_a_past_outage_overrun(ctx, net):
    """L2 was down 09:30–09:45: at 10:00 the rate is fine again, but 36.5 TB are left and the reservation
    carries only 32 TB more. The past slot locates the lost bytes."""
    net.add_outage("L2", t(9, 30), t(9, 45))
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.slow, d.overrun, d.cause, d.links) == (False, True, "link_down", (L2,))
    assert d.remaining_bytes == 36.5 * TB
    assert [(x.start, x.up) for x in d.damage] == [(t(9, 30), False)]


def test_congestion_overruns_and_is_located_past_and_ahead(ctx, net):
    net.add_background(L2, t(9, 30), t(10, 30), 20)                  # L2 now leaves 20 of our 40
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.overrun, d.cause, d.links, d.progress.bytes_sent) == (True, "congestion", (L2,), 13.5 * TB)
    assert [(x.start, x.observed_gbps, x.own_gbps) for x in d.damage] == [
        (t(9, 30), 20, 40), (t(9, 45), 20, 40), (t(10), 20, 40), (t(10, 15), 20, 40)]


def test_slow_on_the_second_reading_is_located_on_the_current_slot(ctx, net):
    assert runtime(ctx, TICK, t(9, 50))["deviations"] == []
    net.add_background(L2, t(9, 50), t(10, 30), 20)
    d = only(runtime(ctx, TICK, t(10, 10)))
    assert (d.slow, d.overrun, d.cause, d.links) == (True, False, "congestion", (L2,))
    assert d.recent_gbps == pytest.approx(20)


def test_slow_with_a_healthy_path_is_unlocated(ctx, net):
    net.add_slowdown("si-1", t(9), t(12), 0.6)                       # e.g. the source disk; every hop is fine
    d = only(runtime(ctx, flow_alert("flow_below_rate", "si-1", t(10), measured_gbps=24), t(10)))
    assert (d.slow, d.cause, d.links, d.damage) == (True, "unlocated", (), ())


def test_a_flow_alert_runs_the_slow_check_only(ctx, net):
    """The alert's own measurement is the throughput; damage ahead is the link branch's, not looked at."""
    net.add_outage("L3", t(11), t(11, 15))
    assert runtime(ctx, flow_alert("flow_below_rate", "si-1", t(10), measured_gbps=39), t(10))["deviations"] == []
    stalled = only(runtime(ctx, flow_alert("flow_stalled", "si-1", t(10, 1)), t(10, 1)))
    assert (stalled.slow, stalled.cause, stalled.damage) == (True, "unlocated", ())


def test_outage_outranks_congestion(ctx, net):
    net.add_background(L3, t(9, 15), t(9, 30), 70)                   # L3 leaves 30 of our 40
    net.add_outage("L2", t(9, 30), t(9, 45))
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.links) == ("link_down", (L2, L3))


def test_past_damage_alone_is_no_deviation(ctx, net):
    """Congestion that cost less than the tolerance and is over: nothing to report."""
    net.add_background(L2, t(9), t(9, 2), 40)                        # 2 min at 0
    assert runtime(ctx, TICK, t(10))["deviations"] == []


def test_late_start_overruns():
    """20 minutes late: 38 TB are left at 10:00 and the reservation carries only 32 TB more."""
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9, 20), 50 * TB)
    net.add_outage("L2", t(9), t(9, 15))                             # before the transfer started: irrelevant
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.slow, d.overrun, d.links, d.damage) == ("late_start", False, True, (), ())


def test_small_lag_that_still_overruns():
    """2 minutes stalled: under the tolerance at 10:00, but by 11:30 the 0.6 TB short is more than 5 % of
    what is left, and the circuit would end before the bytes are through."""
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_background(L2, t(9), t(9, 2), 40)
    assert runtime(ctx, TICK, t(10))["deviations"] == []
    d = only(runtime(ctx, TICK, t(11, 30)))
    assert (d.cause, d.overrun, d.links) == ("congestion", True, (L2,))   # the past slot locates it


def test_bytes_carried():
    profile = [RateSegment(start=t(9), end=t(11), gbps=40)]
    assert bytes_carried(profile, None, t(10), 50 * TB) == 0
    assert bytes_carried(profile, t(9, 20), t(10), 50 * TB) == 12 * TB
    assert bytes_carried(profile, t(9), t(12), 50 * TB) == 36 * TB          # nothing after the profile
    assert bytes_carried(profile, t(9), t(12), 20 * TB) == 20 * TB          # at most the cap


def test_tolerance_boundary():
    assert not is_short(100, 95, 0.05)                               # exactly 5 %: not yet
    assert is_short(100, 94, 0.05)
    assert not is_short(0, 0, 0.05)


@pytest.mark.parametrize("factor, deviates", [(0.96, False), (0.94, True)])
def test_tolerance_on_a_slowed_transfer(ctx, net, factor, deviates):
    net.add_slowdown("si-1", t(9), t(12), factor)
    assert runtime(ctx, TICK, t(9, 30))["deviations"] == []          # first reading: not enough lost yet
    assert bool(runtime(ctx, TICK, t(10))["deviations"]) is deviates


def test_tolerance_comes_from_the_config(ctx, net):
    net.add_slowdown("si-1", t(9), t(12), 0.94)
    ctx.cfg = ctx.cfg.model_copy(update={"progress_lag_tolerance": 0.1})
    runtime(ctx, TICK, t(9, 30))
    assert runtime(ctx, TICK, t(10))["deviations"] == []


def test_recent_rate_from_two_readings(ctx, net):
    assert runtime(ctx, TICK, t(9, 50))["deviations"] == []
    net.add_slowdown("si-1", t(9, 50), t(12), 0.5)
    d = only(runtime(ctx, TICK, t(10, 40)))
    assert d.recent_gbps == pytest.approx(20) and d.slow
    assert ctx.progress_seen["si-1"].sampled_at == t(10, 40)


# ── link branch ───────────────────────────────────────────────────────────

def test_damage_ahead_of_a_running_transfer(ctx, net):
    net.add_outage("L3", t(11), t(11, 15))                           # planned: the forecast knows it
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.links, d.slow, d.overrun) == ("link_down", (L3,), False, False)
    assert [x.start for x in d.damage] == [t(11)]


def test_commitment_not_started_yet():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/2")                         # 12:00–13:06:40 @ 100; nothing sent yet
    net.add_background(L2, t(12, 30), t(13), 30)                     # registered: the forecast knows it
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.progress.started_at, d.overrun) == ("congestion", None, False)
    assert [(x.start, x.observed_gbps, x.own_gbps) for x in d.damage] == [(t(12, 30), 70, 100), (t(12, 45), 70, 100)]


# ── what each event checks ────────────────────────────────────────────────

def test_finished_transfers_are_not_checked():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/1", "q1/T2/2")            # cmt-1 on si-1; cmt-2 = T2 12:00 @ 100 on si-2
    net.start_flow("si-2", t(12), 10**12)                            # 1 TB: done at 12:01:20
    net.start_flow("si-1", t(9, 20), 50 * TB)                        # late: still unfinished when its circuit ends
    assert runtime(ctx, TICK, t(12, 5))["checked"] == ["cmt-1"]


def test_a_slot_that_becomes_current_is_measured(ctx, net):
    """At 09:58 the 10:00 slot holds a forecast. An unplanned outage starts at 09:59; at 10:00 that slot
    is the current one, so it is measured, not read from the forecast."""
    assert runtime(ctx, TICK, t(9, 58))["deviations"] == []
    net.add_outage("L2", t(9, 59), t(10, 30), planned=False)
    out = runtime(ctx, TICK, t(10))
    assert L2 in out["refreshed"]
    assert (only(out).cause, only(out).links) == ("link_down", (L2,))


def test_alerts_select_the_commitments():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/1", "q1/T2/2")            # both along MAIN; cmt-2 at 12:00
    net.start_flow("si-1", t(9), 50 * TB)
    assert runtime(ctx, flow_alert("flow_stalled", "si-1", t(10)), t(10))["checked"] == ["cmt-1"]
    assert runtime(ctx, flow_alert("flow_stalled", "si-9", t(10)), t(10))["checked"] == []
    assert runtime(ctx, link_alert("link_down", L4, t(10)), t(10))["checked"] == []           # not on our paths
    net.add_outage("L2", t(10), t(23), planned=False)
    out = runtime(ctx, link_alert("link_down", "L2", t(10)), t(10, 1))                        # physical id
    assert out["checked"] == ["cmt-1", "cmt-2"]                       # p95: down until 13:00, over both


def test_alert_from_the_mock_telemetry(ctx, net):
    """End to end: telemetry pushes link_down for L2 and graph B takes it from there."""
    alerts = MockAlerts(net)
    subs = [Subscribe(kind="link_down", targets=[L2])]
    net.add_outage("L2", t(10), t(10, 30), planned=False)
    [a] = alerts.poll(subs, t(10, 5))
    d = only(runtime(ctx, a.model_dump(), t(10, 5)))                  # as JSON-like dict, as telemetry sends it
    assert (d.cause, d.links) == ("link_down", (L2,))


def test_malformed_event_is_checked_as_a_tick(ctx, net):
    net.add_outage("L2", t(9, 30), t(9, 45))
    out = runtime(ctx, {"kind": "link_down", "flow_id": "si-1"}, t(10))
    assert out["parsed"] == Tick() and "invalid_event" in out
    assert out["checked"] == ["cmt-1"] and only(out).cause == "link_down"
