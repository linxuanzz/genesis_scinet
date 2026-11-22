"""Runtime demo (step 7e), for presentations: the network agent after commit, scene by scene.

Each scene starts from the same simulated network (slide 3: anl-n02 → esnet-atl → esnet-chi → ornl-n01,
100 Gbps per link, plus a 40 Gbps detour via esnet-nash) with transfers already committed through graph A,
then lets something happen and shows graph B's stages: forecast → detection → assessment → repair → report.

    1 maintenance   a planned outage ahead of a transfer that has not started   link branch, repaired ahead
    2 congestion    unannounced traffic now; the forecast carries it ahead       link alert → repaired ahead
    3 fiber cut     an unplanned outage under a running transfer                 link alert → reroute
    4 slow host     the transfer is slow but every hop is fine                   flow alert → extend only
    5 priority      congestion on a hop two of our transfers share               borrow from the lower priority
    6 no way out    nothing local can meet the deadline                          unresolved → scheduler decides

How to run (from the directory that contains the package):
    python -m <package path>.tests.test_step7e_demo            all scenes
    python -m <package path>.tests.test_step7e_demo 3          one scene
"""

import sys

from ..src.models.schemas import TelemetryAlert
from .helpers import L2, L3, L4, TICK, book, make_committed_ctx, make_ctx, make_net, modify, reports, t, tr
from .printing import PipelineSession

TB = 10**12


def link_alert(kind, link_id, at, **over):
    return TelemetryAlert(alert_id=f"{kind}-{at:%H%M}", kind=kind, link_id=link_id, start=at, observed_at=at,
                          source="telemetry", **over)


def flow_alert(kind, flow_id, at, **over):
    return TelemetryAlert(alert_id=f"{kind}-{at:%H%M}", kind=kind, flow_id=flow_id, start=at, observed_at=at,
                          source="telemetry", **over)


def maintenance():
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/2")                 # T1: 12:00 @ 100 Gbps, not started yet
    s = PipelineSession("Scene 1 · Planned maintenance ahead",
                        "The maintenance calendar schedules L3 down 12:15–12:45, inside T1's reservation. T1 has\n"
                        "not started; there is nothing to measure yet. The forecast already knows, so the periodic\n"
                        "check finds it two hours early and repairs before the transfer begins.", net, ctx)
    s.happens("operations put L3 maintenance 12:15–12:45 into the calendar")
    net.add_outage("L3", t(12, 15), t(12, 45))
    out = s.run(TICK, t(10), "periodic self-check")
    s.print_forecast(L3, t(11, 45), t(13, 15), t(10), "the forecast")
    s.print_commitments()
    net.start_flow(ctx.committed()[0].commitment.circuit_id, t(12), 50 * TB)
    return s, [out], s.finishes(ctx.committed()[0].commitment.circuit_id)


def congestion():
    net = make_net(background_gbps=0)
    ctx = make_ctx(net)
    ctx.cfg = ctx.cfg.model_copy(update={"forecast_decay_seconds": 7200})
    book(ctx, "q2", tr("T2", nbytes=36 * TB, window=(t(12), t(16)), workflow_id="WF-2"), 1)
    modify(ctx, "q2/T2/1", t(12), t(13), 80, reserve_id="rsv-1", now=t(9))   # T2: 12:00–13:00 @ 80 Gbps
    s = PipelineSession("Scene 2 · Unannounced congestion now, a transfer later",
                        "At 10:00 traffic nobody registered takes 70 Gbps of L2 and telemetry alerts. The forecast\n"
                        "starts from what it measures now and fades toward the usual level further ahead (decay 2 h),\n"
                        "so T2's slots from 12:00 already look short: T2 is repaired at 10:00, before it starts.\n"
                        "The forecast is only an estimate: the traffic actually lasts until 12:20, longer than it\n"
                        "assumed. Once T2 runs, the flow branch notices the bytes it lost and extends it again.", net, ctx)
    s.happens("unregistered traffic takes 70 Gbps of L2, 10:00–12:20")
    net.add_background(L2, t(10), t(12, 20), 70, registered=False)
    alert = link_alert("link_capacity_below", L2, t(10), measured_gbps=30)
    out = s.run(alert, t(10), "telemetry alert: link_capacity_below on L2 (30 Gbps left)")
    s.print_forecast(L2, t(10), t(13, 30), t(10), "the forecast after the alert")
    s.print_commitments()
    instance = ctx.committed()[0].commitment.circuit_id
    net.start_flow(instance, t(12), 36 * TB)
    s.happens("T2 starts at 12:00; until 12:20 it gets only 30 Gbps")
    later = s.run(TICK, t(12, 30), "periodic self-check")
    s.print_commitments()
    return s, [out, later], s.finishes(instance)


def fiber_cut():
    net = make_net()
    ctx = make_committed_ctx(net)                            # T1: 09:00 @ 40 Gbps, running
    s = PipelineSession("Scene 3 · Fiber cut under a running transfer",
                        "L2 is cut at 10:00; nobody planned it. The forecast assumes a typical repair (1 h) and a bad\n"
                        "case (3 h), past T1's reservation, so T1 is moved to the detour: the new circuit is set up\n"
                        "and the transfer switched before the old circuit is released.", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    s.happens("L2 is cut at 10:00")
    net.add_outage("L2", t(10), t(23), planned=False)
    out = s.run(link_alert("link_down", "L2", t(10)), t(10), "telemetry alert: link_down on L2")
    s.print_forecast(L2, t(10), t(13, 30), t(10), "the forecast after the alert")
    s.print_commitments()
    return s, [out], s.finishes(ctx.committed()[0].commitment.circuit_id)


def slow_host():
    net = make_net()
    ctx = make_committed_ctx(net)                            # T1: 09:00 @ 40 Gbps, running
    s = PipelineSession("Scene 4 · Slow transfer, healthy network",
                        "From 09:00 the source disk reads at 60 %. Every hop is fine, so more bandwidth or another\n"
                        "path would not help: the agent only proposes a later end, at the rate actually seen.", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    s.happens("T1's source reads at 60 % of the circuit")
    net.add_slowdown("si-1", t(9), t(23), 0.6)
    out = s.run(flow_alert("flow_below_rate", "si-1", t(10), measured_gbps=24), t(10),
                "telemetry alert: flow_below_rate on T1's circuit (24 Gbps)")
    s.print_commitments()
    return s, [out], s.finishes("si-1")


def priority():
    net = make_net(20)                                       # L2 leaves 80 before 12:00
    net.add_background(L4, t(9), t(12), 40)                  # the detour is full
    ctx = make_ctx(net)
    lo = book(ctx, "qL", tr("TL", nbytes=36 * TB, window=(t(9, 30), t(17)), priority=1, workflow_id="WF-L"), 1)
    hi = book(ctx, "qH", tr("TH", nbytes=9 * TB, window=(t(9), t(10, 10)), priority=2, workflow_id="WF-H"), 2)
    s = PipelineSession("Scene 5 · Two of our transfers share a congested hop",
                        "TH (priority 2, due 10:10) and TL (priority 1, due 17:00) both use L2; the detour is full.\n"
                        "Extra traffic squeezes L2, the network shares what is left in proportion, and TH would be\n"
                        "late. TL has slack: it lends rate to TH and still meets its own deadline.", net, ctx)
    net.start_flow(hi, t(9), 9 * TB)
    net.start_flow(lo, t(9, 30), 36 * TB)
    s.happens("60 Gbps more on L2 09:10–09:30")
    net.add_background(L2, t(9, 10), t(9, 30), 60)
    out = s.run(TICK, t(9, 20), "periodic self-check")
    s.print_commitments()
    return s, [out], s.finishes(hi, lo)


def no_way_out():
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(11, 50))), 1)    # 09:00 @ 40, due 11:50
    s = PipelineSession("Scene 6 · Nothing local can meet the deadline",
                        "L2 is down for an hour of maintenance and T1 is due at 11:50: no extension, rate increase,\n"
                        "detour or loan gets it there. The agent reports it once, unresolved; the scheduling agent\n"
                        "decides (here it allows until 14:00 through graph A) and the agent is quiet again.", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    s.happens("L2 maintenance 09:30–10:30")
    net.add_outage("L2", t(9, 30), t(10, 30))
    runs = [s.run(TICK, t(10), "periodic self-check"), s.run(TICK, t(10, 5), "periodic self-check (nothing changed)")]
    s.happens("the scheduling agent extends T1's deadline to 14:00 (graph A: modify)")
    modify(ctx, "q1/T1/1", t(9), t(14), 40, now=t(10, 6))
    runs.append(s.run(TICK, t(10, 10), "periodic self-check"))
    return s, runs, s.finishes("si-1")


SCENES = [maintenance, congestion, fiber_cut, slow_host, priority, no_way_out]


# ── the demo stays true: each scene's key outcome is checked ──────────────

def test_maintenance():
    _, [out], done = maintenance()
    assert [(d.slow, d.overrun, d.cause) for d in out["deviations"]] == [(False, False, "link_down")]
    [(_, cause, outcome, _)] = reports(out)
    assert (cause, outcome) == ("link_down", "repaired")
    [finish] = done.values()
    assert finish is not None and finish <= t(15)


def test_congestion():
    _, [ahead, later], done = congestion()
    assert ahead["short_slots"] and [d.commitment_id for d in ahead["deviations"]] == ["cmt-1"]
    assert [r[2] for r in reports(ahead)] == ["repaired"]
    [finish] = done.values()
    assert finish is not None and finish <= t(16)


def test_fiber_cut():
    _, [out], done = fiber_cut()
    assert reports(out) == [("cmt-1", "link_down", "repaired", "reroute")]
    [finish] = done.values()
    assert finish <= t(15)


def test_slow_host():
    _, [out], _ = slow_host()
    [d] = out["deviations"]
    assert (d.slow, d.cause) == (True, "unlocated")
    assert out["plans"][0].steps == ["extend"] and reports(out) == [("cmt-1", "unlocated", "repaired", "extend")]


def test_priority():
    _, [out], _ = priority()
    assert sorted(r[3] for r in reports(out)) == ["extend", "lend"]


def test_no_way_out():
    _, runs, done = no_way_out()
    assert reports(runs[0]) == [("cmt-1", "link_down", "unresolved", None)] and reports(runs[1]) == []
    assert not reports(runs[2]) and done["si-1"] <= t(14)


if __name__ == "__main__":
    chosen = [SCENES[int(arg) - 1] for arg in sys.argv[1:]] or SCENES
    for scene in chosen:
        scene()
