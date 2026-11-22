"""Uses an explicit approve-first mock scheduler and a mock transfer controller.

Step 7 demo: graph B in five scenarios, one per kind of deviation and one for priority. Each prints the
network, the commitments, every run of graph B (the nodes it ran, the deviations, the forecast, the plan
and the DeviationReports) and when the simulated transfers actually finish.

    outage       L2 down 15 minutes                      → repaired by extend
    congestion   L2 congested, latest_finish tight       → repaired by reroute (make-before-break)
    unlocated    the source slows down, then stalls       → repaired by extend, then updated unresolved forecasts
    priority     TH congested and blocked by TL           → TH repaired by extend, TL lends
    decision     no repair can make latest_finish         → unresolved; the scheduling agent extends it (graph A)

How to run (from the repository root):
    python -m <package path>.tests.test_step7_demo     (e.g. network_agent.tests...)
"""

from .helpers import L2, L4, TICK, book, follow_reroutes, make_committed_ctx, make_ctx, make_net, modify, reports, t, tr
from .printing import RuntimeSession

TB = 10**12


def outage():
    net = make_net()
    ctx = make_committed_ctx(net)
    s = RuntimeSession("Outage: L2 down 09:30–09:45 under T1 (50 TB, 09:00 @ 40 Gbps)", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(9, 45))
    s.event("L2 is down 09:30–09:45; the WMS keeps sending once it is back")
    runs = [s.run(TICK, t(10))]
    s.event("the next tick: the reservation now covers the rest")
    runs.append(s.run(TICK, t(10, 15)))
    return s, runs, s.finishes("si-1")


def congestion():
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(12, 10))), 1)
    modify(ctx, "q1/T1/1", t(9), t(12, 5), 40)
    s = RuntimeSession("Congestion: 20 Gbps more on L2 09:30–10:30, T1 due by 12:10", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_background(L2, t(9, 30), t(10, 30), 20)
    s.event("traffic telemetry cannot see takes 20 of our 40 on L2 until 10:30")
    out = s.run(TICK, t(10))
    s.event("the transfer controller confirmed the switch before the old circuit was released")
    follow_reroutes(net, out, t(10))
    s.print_commitments()
    return s, [out], s.finishes("si-2")


def unlocated():
    net = make_net()
    ctx = make_committed_ctx(net)
    s = RuntimeSession("Unlocated: the source of T1 slows to 60 %, then stalls", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_slowdown("si-1", t(9), t(11), 0.6)
    net.add_slowdown("si-1", t(11), t(23), 0.0)
    s.event("from 09:00 the source disk reads at 60 % of the circuit; every hop is fine")
    runs = [s.run(TICK, t(10))]
    s.event("from 11:00 the source stops sending")
    runs += [s.run(TICK, t(11, 30)), s.run(TICK, t(11, 45))]
    return s, runs, s.finishes("si-1")


def priority():
    net = make_net(20)
    net.add_background(L4, t(9), t(12), 40)
    ctx = make_ctx(net)
    lo = book(ctx, "qL", tr("TL", nbytes=36 * TB, window=(t(9, 30), t(17)), priority=1, workflow_id="WF-L"), 1)
    hi = book(ctx, "qH", tr("TH", nbytes=9 * TB, window=(t(9), t(10, 10)), priority=2, workflow_id="WF-H"), 2)
    s = RuntimeSession("Priority: TH (priority 2) congested, L2 after 09:30 all TL's (priority 1); ALT full", net, ctx)
    net.start_flow(hi, t(9), 9 * TB)
    net.start_flow(lo, t(9, 30), 36 * TB)
    net.add_background(L2, t(9, 10), t(9, 30), 60)
    s.event("60 Gbps more on L2 09:10–09:30 leave TH 20 of its 40")
    out = s.run(TICK, t(9, 20))
    s.print_commitments()
    return s, [out], s.finishes(hi, lo)


def decision():
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(11, 50))), 1)
    s = RuntimeSession("Decision: L2 down 09:30–10:30, T1 due by 11:50", net, ctx)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(10, 30))
    s.event("L2 is down for an hour")
    runs = [s.run(TICK, t(10)), s.run(TICK, t(10, 5))]
    s.event("the scheduling agent decides through graph A: T1 may run until 14:00")
    modify(ctx, "q1/T1/1", t(9), t(14), 40, now=t(10, 6))
    runs.append(s.run(TICK, t(10, 10)))
    return s, runs, s.finishes("si-1")


def test_outage():
    _, runs, done = outage()
    assert reports(runs[0]) == [("cmt-1", "link_down", "repaired", "extend")]
    # still behind, but finishes in its reservation
    assert runs[1]["finishes_in_reservation"] == ["cmt-1"] and "reports" not in runs[1]
    assert done["si-1"] == runs[0]["reports"]["link_down"][0].predicted_finish_p95


def test_congestion():
    _, [out], done = congestion()
    [r] = out["reports"]["congestion"]
    assert (r.action, r.commitment.circuit_id) == ("reroute", "si-2")
    assert done["si-2"] == r.predicted_finish_p95 <= r.latest_finish


def test_unlocated():
    _, runs, done = unlocated()
    assert [reports(o) for o in runs] == [[("cmt-1", "unlocated", "repaired", "extend")],
                                          [("cmt-1", "unlocated", "unresolved", None)],
                                          [("cmt-1", "unlocated", "unresolved", None)]]
    assert runs[1]["reports"]["unlocated"][0].predicted_finish_p95 is not None
    assert runs[2]["reports"]["unlocated"][0].predicted_finish_p95 is None
    assert runs[2]["retry_deferred"] == [] and done["si-1"] is None


def test_priority():
    _, [out], done = priority()
    assert reports(out) == [("cmt-2", "congestion", "repaired", "extend"), ("cmt-1", "congestion", "repaired", "lend")]
    by_id = {r.commitment_id: r for r in out["reports"]["congestion"]}
    assert list(done.values()) == [by_id["cmt-2"].predicted_finish_p95, by_id["cmt-1"].predicted_finish_p95]


def test_decision():
    _, runs, done = decision()
    assert reports(runs[0]) == [("cmt-1", "link_down", "unresolved", None)] and reports(runs[1]) == []
    assert runs[2]["finishes_in_reservation"] == ["cmt-1"] and done["si-1"] <= t(14)


if __name__ == "__main__":
    for scenario in (outage, congestion, unlocated, priority, decision):
        scenario()
