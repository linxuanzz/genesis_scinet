"""Step 7 A: the simulated transfers (progress) and telemetry alerts that feed graph B, and their schemas.

Flows run on the slide-7 network: L2 has 60 Gbps of background before 12:00, so 40 is left there.
1 Gbps for 1 s moves 125 MB, so 40 Gbps for an hour moves 18 TB.
"""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ..src.adapters.telemetry import MockAlerts, MockFlows
from ..src.models.config import load_config
from ..src.models.schemas import RUNTIME_EVENT, FlowProgress, Subscribe, TelemetryAlert, Tick
from ..src.models.topology import Topology
from ..src.sim.sim import MockNetwork
from .helpers import CFG, L2, MAIN, TOPO, make_committed_ctx, make_net, t

TB = 10**12
GB = 10**9


def gb_per_s(gbps):
    """Bytes per second at gbps."""
    return gbps * GB / 8


@pytest.fixture
def net():
    return make_net()


def ours(net, instance_id, gbps, start=t(9), end=t(12), path=MAIN):
    net.add_ours(instance_id, path, start, end, gbps)


def sent(net, instance_id, at):
    return net.flow_trace(instance_id, at).sent


# ── progress ──────────────────────────────────────────────────────────────

def test_not_started(net):
    ours(net, "si-1", 40)
    trace = net.flow_trace("si-1", t(10))
    assert trace.first_byte is None and trace.sent == 0 and trace.finished_at is None


def test_full_rate(net):
    ours(net, "si-1", 40)
    net.start_flow("si-1", t(9), 50 * TB)
    assert sent(net, "si-1", t(10)) == pytest.approx(18 * TB)
    assert net.flow_trace("si-1", t(10)).first_byte == t(9)


def test_late_start(net):
    ours(net, "si-1", 40)
    net.start_flow("si-1", t(9, 20), 50 * TB)
    trace = net.flow_trace("si-1", t(10))
    assert trace.first_byte == t(9, 20) and trace.sent == pytest.approx(gb_per_s(40) * 40 * 60)


def test_bytes_only_move_inside_the_reservation(net):
    ours(net, "si-1", 40, start=t(10), end=t(11))
    net.start_flow("si-1", t(9), 50 * TB)                       # started before its circuit exists
    trace = net.flow_trace("si-1", t(12))
    assert trace.first_byte == t(10) and trace.sent == pytest.approx(18 * TB)   # and nothing after 11:00


def test_congestion_outage_and_slowdown(net):
    """min(reserved, what the tightest hop leaves) × the factor outside the links."""
    ours(net, "si-1", 40)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_background(L2, t(9), t(9, 10), 20)                  # L2 leaves 20
    net.add_outage("L3", t(9, 10), t(9, 20))                    # 0
    net.add_slowdown("si-1", t(9, 20), t(9, 30), 0.5)           # 40 × 0.5
    per_10_min = [sent(net, "si-1", t(9, m + 10)) - sent(net, "si-1", t(9, m)) for m in (0, 10, 20, 30)]
    assert per_10_min == pytest.approx([gb_per_s(g) * 600 for g in (20, 0, 20, 40)])


def test_our_flows_share_a_congested_hop_by_reserved_rate():
    net = MockNetwork(Topology.from_dict(TOPO))
    ours(net, "si-1", 60)
    ours(net, "si-2", 20)
    net.add_background(L2, t(9), t(12), 60)                     # L2 leaves 40 for 80 reserved → 30 and 10
    net.start_flow("si-1", t(9), 50 * TB)
    net.start_flow("si-2", t(9), int(gb_per_s(10) * 600))       # finishes at 09:10, freeing its share
    a = net.flow_trace("si-1", t(9, 20))
    assert net.flow_trace("si-2", t(10)).finished_at == t(9, 10)
    assert a.segments == [(t(9), t(9, 10), 30), (t(9, 10), t(9, 20), 40)]


def test_finish_caps_the_bytes(net):
    ours(net, "si-1", 40)
    net.start_flow("si-1", t(9), TB)                            # 1 TB at 40 Gbps: 200 s
    trace = net.flow_trace("si-1", t(10))
    assert trace.sent == TB and trace.finished_at == t(9) + timedelta(seconds=200)


def test_bad_flow_input(net):
    with pytest.raises(KeyError):
        net.start_flow("si-9", t(9), TB)
    ours(net, "si-1", 40)
    with pytest.raises(ValueError):
        net.add_slowdown("si-1", t(9), t(10), 1.5)


def test_mock_flows_reports_progress(net):
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9, 20), 50 * TB)
    p = ctx.flows.progress("si-1", t(10))
    assert isinstance(ctx.flows, MockFlows)
    assert (p.flow_id, p.started_at, p.bytes_sent, p.sampled_at) == ("si-1", t(9, 20), 12 * TB, t(10))


# ── alerts ────────────────────────────────────────────────────────────────

def test_link_state_alerts_once_per_change(net):
    alerts = MockAlerts(net)
    subs = [Subscribe(kind="link_down", targets=["L2"]), Subscribe(kind="link_up", targets=["L2"])]
    net.add_outage("L2", t(10), t(10, 30))
    assert alerts.poll(subs, t(9, 50)) == []
    down = alerts.poll(subs, t(10, 5))
    assert [(a.kind, a.link_id, a.start, a.end) for a in down] == [("link_down", "L2", t(10), None)]
    assert alerts.poll(subs, t(10, 10)) == []                   # still down: not sent again
    up = alerts.poll(subs, t(10, 40))
    assert [(a.kind, a.start) for a in up] == [("link_up", t(10, 30))]


def test_capacity_below_threshold(net):
    """The threshold is what we booked; background on L2 leaves 40 before 12:00."""
    alerts = MockAlerts(net)
    sub = Subscribe(kind="link_capacity_below", targets=[L2], threshold_gbps=50, start=t(11), end=t(13))
    [a] = alerts.poll([sub], t(10))
    assert (a.start, a.end, a.measured_gbps) == (t(11), t(12), 40)
    assert "threshold_gbps" not in a.model_dump(mode="json")
    now = Subscribe(kind="link_capacity_below", targets=[L2], threshold_gbps=50)
    assert [a.start for a in MockAlerts(net).poll([now], t(10))] == [t(10)]
    assert MockAlerts(net).poll([now], t(12)) == []


def test_flow_alerts(net):
    ours(net, "si-1", 40)
    net.start_flow("si-1", t(9), 2 * TB)                        # 400 s at full rate
    net.add_slowdown("si-1", t(9), t(9, 2), 0.5)
    net.add_outage("L3", t(9, 2), t(9, 4))
    alerts = MockAlerts(net)
    subs = [Subscribe(kind="flow_below_rate", targets=["si-1"], threshold_gbps=36, min_duration_seconds=60),
            Subscribe(kind="flow_stalled", targets=["si-1"], min_duration_seconds=60),
            Subscribe(kind="flow_finished", targets=["si-1"])]
    slow = alerts.poll(subs, t(9, 1))
    assert [(a.kind, a.measured_gbps) for a in slow] == [("flow_below_rate", 20)]
    assert "threshold_gbps" not in slow[0].model_dump(mode="json")
    assert [a.kind for a in alerts.poll(subs, t(9, 3))] == ["flow_stalled"]   # below rate continues: not resent
    done = alerts.poll(subs, t(10))
    finish = t(9, 4) + timedelta(seconds=(2 * TB - gb_per_s(20) * 120) / gb_per_s(40))
    assert [(a.kind, a.start) for a in done] == [("flow_finished", finish)]


# ── schemas ───────────────────────────────────────────────────────────────

def alert(**over):
    base = dict(alert_id="a1", kind="link_down", link_id=L2, start=t(10), observed_at=t(10), source="mock")
    return TelemetryAlert(**(base | over))


@pytest.mark.parametrize("over", [
    {"link_id": None},                                          # a link alert without its link
    {"flow_id": "si-1"},                                        # ... with a flow
    {"kind": "flow_stalled", "link_id": None},                  # a flow alert without its flow
    {"kind": "link_capacity_below"},                            # no measured value
    {"kind": "flow_below_rate", "link_id": None, "flow_id": "si-1"},  # no measured value
    {"end": t(9)},                                              # end before start
])
def test_bad_alerts(over):
    with pytest.raises(ValidationError):
        alert(**over)


@pytest.mark.parametrize("target", [
    {"kind": "link_capacity_below", "link_id": L2},
    {"kind": "flow_below_rate", "link_id": None, "flow_id": "si-1"},
])
def test_threshold_alert_message_contains_measurement_only(target):
    message = alert(**target, measured_gbps=0)
    assert RUNTIME_EVENT.validate_json(message.model_dump_json()) == message
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        alert(**target, measured_gbps=0, threshold_gbps=50)


@pytest.mark.parametrize("fields", [
    {"kind": "link_down", "targets": []},
    {"kind": "link_down", "targets": [L2, L2]},
    {"kind": "flow_below_rate", "targets": ["si-1"], "min_duration_seconds": 60},          # no threshold
    {"kind": "flow_stalled", "targets": ["si-1"]},                                          # no window
    {"kind": "link_down", "targets": [L2], "threshold_gbps": 10},
    {"kind": "link_capacity_below", "targets": [L2], "threshold_gbps": 10, "start": t(10)},
    {"kind": "link_down", "targets": [L2], "start": t(10), "end": t(11)},
])
def test_bad_subscriptions(fields):
    with pytest.raises(ValidationError):
        Subscribe(**fields)


def test_flow_progress_consistency():
    with pytest.raises(ValidationError):
        FlowProgress(flow_id="si-1", started_at=None, bytes_sent=1, sampled_at=t(10), source="mock")
    with pytest.raises(ValidationError):
        FlowProgress(flow_id="si-1", started_at=t(11), bytes_sent=0, sampled_at=t(10), source="mock")


def test_runtime_event_parses_both_kinds():
    assert RUNTIME_EVENT.validate_python({"kind": "tick"}) == Tick()
    parsed = RUNTIME_EVENT.validate_python(alert(kind="link_up").model_dump())
    assert isinstance(parsed, TelemetryAlert) and parsed.kind == "link_up"
    with pytest.raises(ValidationError):
        RUNTIME_EVENT.validate_python({"kind": "reboot"})


@pytest.mark.parametrize("tolerance", [-0.1, 1])
def test_config_rejects_tolerance_out_of_range(tolerance):
    with pytest.raises(ValidationError):
        load_config({**CFG, "progress_lag_tolerance": tolerance})
