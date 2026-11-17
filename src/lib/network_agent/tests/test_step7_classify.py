"""Step 7 A: graph B's classify_event: which commitments deviate, and why (link_down / congestion /
late_start / unlocated).

Unless a test says otherwise, the agent has committed cmt-1 = q1/T1/1 on si-1: 09:00–11:46:40 @ 40 Gbps
along MAIN (L2 has 40 left before 12:00), and the WMS starts its 50 TB at 09:00. 40 Gbps for an hour
moves 18 TB; the tolerance (CFG) is 5 % of what is due.
"""

import pytest

from ..src.adapters.telemetry import MockAlerts
from ..src.models.schemas import RateSegment, Subscribe, TelemetryAlert, Tick
from ..src.runtime.deviation import due_bytes, is_behind
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


def flow_alert(kind, flow_id, at):
    return TelemetryAlert(alert_id="a2", kind=kind, flow_id=flow_id, start=at, observed_at=at, source="mock")


def only(out):
    [d] = out["deviations"]
    return d


# ── the three causes ──────────────────────────────────────────────────────

def test_on_track_ends(ctx):
    out = runtime(ctx, TICK, t(10))
    assert out["deviations"] == [] and out["checked"] == ["cmt-1"]
    assert visited(ctx, TICK, t(10)) == ["deduplicate_event", "classify_event", "remember_event"]


def test_outage(net, ctx):
    net.add_outage("L2", t(9, 30), t(9, 45))
    assert visited(ctx, TICK, t(10))[:3] == ["deduplicate_event", "classify_event", "scan_path"]
    d = only(runtime(make_outage_ctx(), TICK, t(10)))
    assert (d.cause, d.links, d.behind) == ("link_down", (L2,), True)
    assert (d.due_bytes, d.progress.bytes_sent, d.lag_bytes) == (18 * TB, 13.5 * TB, 4.5 * TB)
    assert [(x.start, x.up) for x in d.damage] == [(t(9, 30), False)]         # past damage locates the lag


def make_outage_ctx():
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(9, 45))
    return ctx


def test_congestion(net, ctx):
    net.add_background(L2, t(9, 30), t(10, 30), 20)                  # L2 now leaves 20 of our 40
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.links, d.progress.bytes_sent) == ("congestion", (L2,), 13.5 * TB)
    assert [(x.start, x.observed_gbps, x.own_gbps) for x in d.damage] == [
        (t(9, 30), 20, 40), (t(9, 45), 20, 40), (t(10), 20, 40), (t(10, 15), 20, 40)]
    assert d.remaining_bytes == 50 * TB - 13.5 * TB


def test_unlocated(net, ctx):
    net.add_slowdown("si-1", t(9), t(12), 0.6)                       # e.g. the source disk; every hop is fine
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.links, d.damage, d.behind) == ("unlocated", (), (), True)


def test_outage_outranks_congestion(net, ctx):
    net.add_background(L3, t(9, 15), t(9, 30), 70)                   # L3 leaves 30 of our 40
    net.add_outage("L2", t(9, 30), t(9, 45))
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.links) == ("link_down", (L2, L3))


# ── link level: not started yet, or ahead of us ────────────────────────────

def test_damage_ahead_of_a_running_transfer(net, ctx):
    net.add_outage("L3", t(11), t(11, 15))                           # planned: telemetry already knows
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.links, d.behind, d.lag_bytes) == ("link_down", (L3,), False, 0)
    assert [x.start for x in d.damage] == [t(11)]


def test_commitment_not_started_yet():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/2")                         # 12:00–13:06:40 @ 100; nothing sent yet
    net.add_background(L2, t(12, 30), t(13), 30)
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.progress.started_at, d.due_bytes, d.behind) == ("congestion", None, 0, False)
    assert [(x.start, x.observed_gbps, x.own_gbps) for x in d.damage] == [(t(12, 30), 70, 100), (t(12, 45), 70, 100)]


def test_past_damage_alone_is_no_deviation(net, ctx):
    """Congestion that cost less than the tolerance and is over: nothing to report."""
    net.add_background(L2, t(9), t(9, 2), 40)                        # 2 min at 0 → 3.3 % behind at 10:00
    assert runtime(ctx, TICK, t(10))["deviations"] == []


# ── late start and overrun ────────────────────────────────────────────────

def test_late_start_is_not_behind_but_overruns():
    """20 minutes late: never behind (due counts from the actual start), but 38 TB are left at 10:00 and the
    reservation carries only 32 TB more, short by more than 5 % of them."""
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9, 20), 50 * TB)
    net.add_outage("L2", t(9), t(9, 15))                             # before the transfer started: irrelevant
    d = only(runtime(ctx, TICK, t(10)))
    assert (d.cause, d.behind, d.overrun, d.links, d.damage) == ("late_start", False, True, (), ())


def test_small_lag_that_still_overruns():
    """2 minutes stalled: under the tolerance at 10:00 (see above), but by 11:30 the 0.6 TB short is more
    than 5 % of what is left, and the circuit would end before the bytes are through."""
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_background(L2, t(9), t(9, 2), 40)
    assert runtime(ctx, TICK, t(10))["deviations"] == []
    d = only(runtime(ctx, TICK, t(11, 30)))
    assert (d.cause, d.behind, d.overrun, d.links) == ("congestion", False, True, (L2,))   # the past slot locates it


def test_due_counts_from_the_actual_start():
    profile = [RateSegment(start=t(9), end=t(11), gbps=40)]
    assert due_bytes(profile, None, t(10), 50 * TB) == 0
    assert due_bytes(profile, t(9, 20), t(10), 50 * TB) == 12 * TB             # not 18 TB from 09:00
    assert due_bytes(profile, t(9), t(12), 50 * TB) == 36 * TB                 # nothing due after the profile
    assert due_bytes(profile, t(9), t(12), 20 * TB) == 20 * TB                 # at most the size


# ── tolerance ─────────────────────────────────────────────────────────────

def test_tolerance_boundary():
    assert not is_behind(100, 95, 0.05)                               # exactly 5 %: not yet
    assert is_behind(100, 94, 0.05)
    assert not is_behind(0, 0, 0.05)


@pytest.mark.parametrize("factor, deviates", [(0.96, False), (0.94, True)])
def test_tolerance_on_a_slowed_transfer(net, ctx, factor, deviates):
    net.add_slowdown("si-1", t(9), t(12), factor)
    assert bool(runtime(ctx, TICK, t(10))["deviations"]) is deviates


def test_tolerance_comes_from_the_config(net, ctx):
    net.add_slowdown("si-1", t(9), t(12), 0.94)
    ctx.cfg = ctx.cfg.model_copy(update={"progress_lag_tolerance": 0.1})
    assert runtime(ctx, TICK, t(10))["deviations"] == []


# ── what each event checks ────────────────────────────────────────────────

def test_finished_transfers_are_not_checked():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/1", "q1/T2/2")            # cmt-1 on si-1; cmt-2 = T2 12:00 @ 100 on si-2
    net.start_flow("si-2", t(12), 10**12)                            # 1 TB: done at 12:01:20
    net.start_flow("si-1", t(9, 20), 50 * TB)                        # late: still unfinished when its circuit ends
    assert runtime(ctx, TICK, t(12, 5))["checked"] == ["cmt-1"]


def test_a_tick_refreshes_only_stale_observations_an_alert_forces_them(net, ctx):
    """An outage starts right after a tick refreshed L2: the next tick still reads the valid (old)
    observations and the lag is under the tolerance, while a link_down alert pulls L2 afresh."""
    first = runtime(ctx, TICK, t(9, 58))
    assert first["deviations"] == [] and L2 in first["refreshed"]
    net.add_outage("L2", t(9, 59), t(10, 30))                        # observations valid until 10:03
    later = runtime(ctx, TICK, t(10))
    assert later["deviations"] == [] and later["refreshed"] == []
    out = runtime(ctx, link_alert("link_down", "L2", t(9, 59)), t(10))
    assert L2 in out["refreshed"]
    d = only(out)
    assert (d.cause, d.links, d.behind) == ("link_down", (L2,), False)  # current and future slots are down


def test_alerts_select_the_commitments():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/1", "q1/T2/2")            # both along MAIN
    net.start_flow("si-1", t(9), 50 * TB)
    assert runtime(ctx, flow_alert("flow_stalled", "si-1", t(10)), t(10))["checked"] == ["cmt-1"]
    assert runtime(ctx, flow_alert("flow_stalled", "si-9", t(10)), t(10))["checked"] == []
    assert runtime(ctx, link_alert("link_up", L4, t(10)), t(10))["checked"] == []           # not on our paths
    assert runtime(ctx, link_alert("link_up", "L2", t(10)), t(10))["checked"] == ["cmt-1", "cmt-2"]  # physical id


def test_alert_from_the_mock_telemetry(net, ctx):
    """End to end: telemetry pushes link_down for L2 and graph B takes it from there."""
    alerts = MockAlerts(net)
    subs = [Subscribe(kind="link_down", targets=[L2])]
    net.add_outage("L2", t(10), t(10, 30))
    [a] = alerts.poll(subs, t(10, 5))
    d = only(runtime(ctx, a.model_dump(), t(10, 5)))                  # as JSON-like dict, as telemetry sends it
    assert (d.cause, d.links) == ("link_down", (L2,))


def test_malformed_event_is_checked_as_a_tick(net, ctx):
    net.add_outage("L2", t(9, 30), t(9, 45))
    out = runtime(ctx, {"kind": "link_down", "flow_id": "si-1"}, t(10))
    assert out["parsed"] == Tick() and "invalid_event" in out
    assert out["checked"] == ["cmt-1"] and only(out).cause == "link_down"


def test_recent_rate_from_two_readings(net, ctx):
    assert runtime(ctx, TICK, t(9, 50))["deviations"] == []
    net.add_slowdown("si-1", t(9, 50), t(12), 0.5)
    d = only(runtime(ctx, TICK, t(10, 40)))                          # 50 min at 20 instead of 40: 7.5 TB short
    assert d.recent_gbps == pytest.approx(20)
    assert ctx.progress_seen["si-1"].sampled_at == t(10, 40)
