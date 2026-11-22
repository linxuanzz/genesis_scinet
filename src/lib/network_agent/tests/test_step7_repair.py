"""Step 7 C: graph B's local repairs (extend, increase, reroute, borrow), their rollback, priority, and
the shared operations and mock behaviour they rest on.

Unless a test says otherwise, the agent has committed cmt-1 = q1/T1/1 on si-1: 09:00–11:46:40 @ 40 Gbps
along MAIN (L2 has 40 left before 12:00), latest_finish 15:00, and the WMS starts its 50 TB at 09:00.
After every repair the simulated transfer is run to its end, to check that it finishes when graph B said.
"""

from datetime import timedelta

import pytest

from ..src.adapters.sense import SenseError, added_spans
from ..src.models.schemas import RateSegment, ServiceIntent, Terminal
from ..src.runtime.repair import RulePolicy
from ..src.shared.reclaim import sweep_expired
from ..src.state.ledger import InsufficientCapacity
from .helpers import (ALT, L2, L4, MAIN, TICK, book, follow_reroutes, make_committed_ctx, make_ctx, make_net, modify,
                      reports, runtime, t, tr)

TB = 10**12


def sec(s):
    return timedelta(seconds=s)


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    return ctx


def one_report(out):
    [r] = [r for rs in out["reports"].values() for r in rs]
    return r


def own(ctx, link, hh, mm=0):
    return ctx.ledger.own(link, ctx.ledger.slots_covering(t(hh, mm), t(hh, mm) + sec(1))[0])


def finished(net, instance_id):
    return net.flow_trace(instance_id, t(23)).finished_at


# ── extend ────────────────────────────────────────────────────────────────

def test_extend_after_an_outage(net, ctx):
    net.add_outage("L2", t(9, 30), t(9, 45))
    r = one_report(runtime(ctx, TICK, t(10)))
    end = t(12, 1) + sec(40)
    assert (r.outcome, r.action, r.predicted_finish_p95) == ("repaired", "extend", end)
    seg = r.commitment.rate_profile[0]
    assert (seg.start, seg.end, seg.gbps) == (t(9), end, 40)
    assert (r.commitment.circuit_id, r.commitment.binding.vlan) == ("si-1", 3001)                 # same circuit
    assert ctx.commitments["cmt-1"] == r.commitment
    assert ctx.reservations["rsv-1"].reserved_offers[0].placement.end == end
    assert [own(ctx, link, 12) for link in MAIN] == [40, 40, 40]                # booked into the 12:00 slot
    assert net._ours["si-1"][1].end == end                                     # SENSE holds it too
    assert finished(net, "si-1") == end


def test_extend_for_a_late_start(net):
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9, 20), 50 * TB)
    r = one_report(runtime(ctx, TICK, t(10)))
    assert (r.cause, r.action, r.predicted_finish_p95) == ("late_start", "extend", t(12, 6) + sec(40))
    assert finished(net, "si-1") == t(12, 6) + sec(40)


def test_extend_for_an_unlocated_slowdown(net, ctx):
    """The assessment keeps the 24 Gbps seen, so the reservation runs at 40 until 39.2 TB are through at 24."""
    net.add_slowdown("si-1", t(9), t(15), 0.6)
    r = one_report(runtime(ctx, TICK, t(10)))
    p95 = t(10) + sec(39.2 * TB * 8 / 24e9)
    assert (r.cause, r.action, r.predicted_finish_p95) == ("unlocated", "extend", p95)
    assert r.commitment.rate_profile[0].end == p95.replace(microsecond=0) + sec(1)     # ends on a whole second
    assert finished(net, "si-1") == p95


def test_extend_across_damage_already_held(net, ctx):
    """Congestion until 10:30 leaves 20 of the 40 booked on L2: the extension keeps those slots as they
    are and only adds 12:00–12:16:40, so it is not refused for the capacity lost there."""
    net.add_background(L2, t(9, 30), t(10, 30), 20)
    r = one_report(runtime(ctx, TICK, t(10)))
    assert (r.action, r.predicted_finish_p95) == ("extend", t(12, 16) + sec(40))
    assert own(ctx, L2, 10) == 40 and finished(net, "si-1") == t(12, 16) + sec(40)


# ── increase ────────────────────────────────────────────────────────────

def test_increase_when_extending_is_too_late():
    """T has an approved reservation until 10:10. After an outage, 50 Gbps recovers the loss by 10:08
    using free capacity, without moving the approved end or changing another commitment."""
    net = make_net(50)
    ctx = make_ctx(net)
    si = book(ctx, "q1", tr("T", nbytes=18 * TB, window=(t(9), t(10, 10))), 2)
    assert ctx.commitments["cmt-1"].rate_profile[0].gbps == 40
    modify(ctx, "q1/T/2", t(9), t(10, 10), 40)
    net.start_flow(si, t(9), 18 * TB)
    net.add_outage("L2", t(9, 15), t(9, 30))
    out = runtime(ctx, TICK, t(9, 40))
    r = one_report(out)
    seg = r.commitment.rate_profile[0]
    assert (r.action, seg.start, seg.end, seg.gbps) == ("increase", t(9), t(10, 10), 50)
    assert own(ctx, L2, 9) == 40 and own(ctx, L2, 9, 45) == 50                 # the slots over keep their 40
    assert finished(net, si) == t(10, 8)
    assert net.flow_trace(si, t(9, 40)).sent == 7.5 * TB                     # the past is not rewritten


# ── reroute ───────────────────────────────────────────────────────────────

@pytest.fixture
def tight():
    """Congestion on L2 09:30–10:30 (20 of our 40) and latest_finish 12:10: at 10:00 extending runs to
    12:16:40 and MAIN has no more than 40 before 12:00, so only ALT can make it: 36.5 TB @ 40 → 12:01:40."""
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(12, 10))), 1)
    modify(ctx, "q1/T1/1", t(9), t(12, 5), 40)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_background(L2, t(9, 30), t(10, 30), 20)
    return net, ctx


def test_reroute(tight):
    net, ctx = tight
    out = runtime(ctx, TICK, t(10))
    r = one_report(out)
    seg = r.commitment.rate_profile[0]
    assert (r.action, r.commitment_id) == ("reroute", "cmt-1")
    assert (r.commitment.circuit_id, r.commitment.binding.vlan) == ("si-2", 3002)                 # a new circuit
    assert (seg.start, seg.end, seg.gbps, r.predicted_finish_p95) == (t(10), t(12, 1) + sec(40), 40, t(12, 1) + sec(40))
    reserved_offer = ctx.reservations["rsv-1"].reserved_offers[0]
    assert reserved_offer.placement.path == ALT
    assert (reserved_offer.request.bytes, reserved_offer.instance_id) == (36.5 * TB, "si-2")
    assert ctx.sense.state("si-1").state == "cancelled" and own(ctx, L2, 10) == 0      # the old one is given back
    assert own(ctx, L4, 10) == 40
    follow_reroutes(net, out, t(10))
    assert finished(net, "si-2") == t(12, 1) + sec(40)
    assert runtime(ctx, TICK, t(10, 30))["deviations"] == []


def test_reroute_keeps_the_old_circuit_as_an_orphan_if_its_cancel_fails(tight):
    net, ctx = tight
    ctx.sense.fail_next("cancel")
    assert one_report(runtime(ctx, TICK, t(10))).action == "reroute"
    assert ctx.orphans == {"si-1": "rsv-1/q1/T1/1"} and own(ctx, L2, 10) == 40         # still held ...
    assert sweep_expired(ctx, t(10, 1)).orphans == ["si-1"] and own(ctx, L2, 10) == 0  # ... until the sweep


@pytest.mark.parametrize("op", ["propagate", "commit"])
def test_a_failed_reroute_is_undone(tight, op):
    net, ctx = tight
    ctx.sense.fail_next(op)
    out = runtime(ctx, TICK, t(10))
    assert reports(out) == [("cmt-1", "congestion", "unresolved", None)]
    assert [why.split(":")[0] for why in out["repair_results"][0].tried] == ["extend", "increase", "reroute"]
    assert own(ctx, L4, 10) == 0 and own(ctx, L2, 10) == 40 and ctx.orphans == {}
    assert [s.state for s in ctx.sense._states.values()] == ["committed"] + (["cancelled"] if op == "commit" else [])


def test_a_refused_extension_is_rolled_back_and_the_next_step_tried(net, ctx):
    """SENSE refuses the extension; later steps cannot preserve the old end, so the failure is reported."""
    net.add_outage("L2", t(9, 30), t(9, 45))
    ctx.sense.fail_next("modify")
    out = runtime(ctx, TICK, t(10))
    assert one_report(out).outcome == "unresolved"
    assert [reason.split(":")[0] for reason in out["repair_results"][0].tried] == ["extend", "increase", "reroute"]
    assert own(ctx, L2, 12) == 0                                              # the extension did not stay


# ── borrow and priority ───────────────────────────────────────────────────

@pytest.fixture
def two_priorities():
    """L2 leaves 80 and ALT has nothing left. TL (priority 1, 36 TB, by 17:00) is booked 09:30–10:30 @ 80;
    TH (priority 2, 9 TB, by deadline) 09:00–09:30 @ 40. 60 Gbps of background 09:10–09:30 leave TH 20.
    At 09:20 TH has 3 TB left after 09:30, where TL takes all of L2."""
    def make(deadline=t(10, 10)):
        net = make_net(20)
        net.add_background(L4, t(9), t(12), 40)
        ctx = make_ctx(net)
        lo = book(ctx, "qL", tr("TL", nbytes=36 * TB, window=(t(9, 30), t(17)), priority=1, workflow_id="WF-L"), 1)
        hi = book(ctx, "qH", tr("TH", nbytes=9 * TB, window=(t(9), deadline), priority=2, workflow_id="WF-H"), 2)
        net.start_flow(hi, t(9), 9 * TB)
        net.start_flow(lo, t(9, 30), 36 * TB)
        net.add_background(L2, t(9, 10), t(9, 30), 60)
        return net, ctx, hi, lo
    return make


def test_borrow_the_least_slack_that_does(two_priorities):
    """TL steps down 70, 60, 50, 40: at 40 L2 leaves TH its 40 after 09:30, so TH ends 09:40 and TL 11:30."""
    net, ctx, hi, lo = two_priorities()
    out = runtime(ctx, TICK, t(9, 20))
    by_id = {r.commitment_id: r for r in out["reports"]["congestion"]}
    h, low = by_id["cmt-2"], by_id["cmt-1"]
    assert (h.action, h.predicted_finish_p95) == ("extend", t(9, 40))
    assert (low.action, low.lent_to, low.commitment.rate_profile[0].gbps, low.predicted_finish_p95) == (
        "lend", "cmt-2", 40, t(11, 30))
    assert low.predicted_finish_p95 <= low.latest_finish
    assert (finished(net, hi), finished(net, lo)) == (t(9, 40), t(11, 30))


def test_lenders_are_put_back_if_borrowing_does_not_help(two_priorities):
    """By 09:35 TH cannot make it, however much TL gives: L2 is congested until 09:30 and TH may not run
    faster than 40 there. TL keeps its 80."""
    net, ctx, hi, lo = two_priorities(deadline=t(9, 35))
    out = runtime(ctx, TICK, t(9, 20))
    assert reports(out) == [("cmt-2", "congestion", "unresolved", None)]
    assert out["repair_results"][0].tried[-1].startswith("borrow: lending")
    assert ctx.commitments["cmt-1"].rate_profile[0].gbps == 80 and finished(net, lo) == t(10, 30)


def test_higher_priority_is_repaired_first():
    """TA and TB, 18 TB each, both 09:00–10:00 @ 40 on MAIN, where L2 leaves 80 (40 after 10:00). Both lose
    15 minutes to an outage and need L2 for 15 more minutes after 10:00, where only one fits: the higher
    priority extends after approval and the other is reported unresolved."""
    def run(prio_a, prio_b):
        net = make_net(20)
        net.add_background(L2, t(10), t(11), 40)
        ctx = make_ctx(net)
        a = book(ctx, "qa", tr("TA", nbytes=18 * TB, window=(t(9), t(15)), priority=prio_a), 1)   # 09:00 @ 80 ...
        modify(ctx, "qa/TA/1", t(9), t(10), 40)                                                   # ... made 40
        b = book(ctx, "qb", tr("TB", nbytes=18 * TB, window=(t(9), t(15)), priority=prio_b), 1)
        for si in (a, b):
            net.start_flow(si, t(9), 18 * TB)
        net.add_outage("L2", t(9, 15), t(9, 30))
        return {r.commitment_id: r.action for r in runtime(ctx, TICK, t(9, 40))["reports"]["link_down"]}
    assert run(1, 2) == {"cmt-2": "extend", "cmt-1": None}
    assert run(2, 1) == {"cmt-1": "extend", "cmt-2": None}


# ── the rule policy ───────────────────────────────────────────────────────

class Recording(RulePolicy):
    """RulePolicy that records the plan it makes and tries none of it."""

    def __init__(self):
        self.plans = []

    def plan_local_repair(self, ctx, assessment, now):
        self.plans.append(super().plan_local_repair(ctx, assessment, now))
        return []


def plan_of(ctx, now):
    policy = Recording()
    runtime(ctx, TICK, now, policy=policy)
    [steps] = policy.plans
    return steps


def started(net, at, nbytes=50 * TB):
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", at, nbytes)
    return ctx


def test_plan_for_each_cause():
    net = make_net()
    ctx = started(net, t(9))
    net.add_slowdown("si-1", t(9), t(15), 0.6)
    assert plan_of(ctx, t(10)) == ["extend"]                           # off the path: only more time helps

    net = make_net()
    assert plan_of(started(net, t(9, 20)), t(10)) == ["extend", "increase", "reroute"]   # late: nobody lends

    net = make_net()
    ctx = started(net, t(9))
    net.add_outage("L2", t(9, 30), t(9, 45))
    assert plan_of(ctx, t(10)) == ["extend", "increase", "reroute"]   # no lower priority to borrow from


def test_plan_borrows_for_a_network_cause(two_priorities):
    _, ctx, *_ = two_priorities()
    assert plan_of(ctx, t(9, 20)) == ["extend", "increase", "reroute", "borrow"]


# ── what the repairs rest on ──────────────────────────────────────────────

def test_ledger_replace_checks_only_what_is_added(net):
    ctx = make_ctx(net)
    ctx.ledger.pending("b", MAIN, [RateSegment(start=t(9), end=t(10), gbps=40)])
    net.add_outage("L2", t(9, 15), t(9, 30))
    ctx.ledger.apply(ctx.telemetry.link_samples([L2], t(9), t(10), t(9)))
    ctx.ledger.replace("b", [RateSegment(start=t(9), end=t(10, 30), gbps=40)], now=t(9, 40))   # across the outage
    with pytest.raises(InsufficientCapacity):
        ctx.ledger.replace("b", [RateSegment(start=t(9), end=t(10, 30), gbps=50)], now=t(9, 10))
    ctx.ledger.replace("b", [RateSegment(start=t(9), end=t(10, 30), gbps=20)], now=t(9, 40))
    assert [own(ctx, L2, h, m) for h, m in ((9, 15), (9, 30), (10, 15))] == [40, 20, 20]  # the slots over keep 40


def intent(start, end, gbps):
    return ServiceIntent(alias="x", terminals=[Terminal(uri="anl-n02"), Terminal(uri="ornl-n01")],
                         capacity_mbps=gbps * 1000, qos_class="guaranteedCapped", start=start, end=end,
                         path_inclusion=list(MAIN))


def test_sense_admits_only_from_now_and_only_what_is_added(net):
    ctx = make_ctx(net)
    s = ctx.sense.propagate(intent(t(9), t(10), 40), now=t(9))
    net.add_background(L2, t(9, 30), t(10), 30)                       # L2 now leaves 10 there
    ctx.sense.modify(s.instance_id, intent(t(9), t(10, 30), 40), now=t(9, 40))         # kept, and extended
    with pytest.raises(SenseError):
        ctx.sense.modify(s.instance_id, intent(t(9), t(10, 30), 50), now=t(9, 40))     # more, where there is none
    ctx.sense.cancel(s.instance_id, now=t(9, 40))
    net.add_background(L2, t(9), t(9, 10), 40)                        # nothing left on L2 before 09:10
    assert ctx.sense.propagate(intent(t(9), t(9, 20), 10), now=t(9, 10)).state == "reserved"   # its past is not checked
    assert added_spans(t(9), t(10), 40, t(9), t(11), 40, t(9, 30)) == [(t(10), t(11))]
    assert added_spans(t(9), t(10), 40, t(9), t(10), 50, t(9, 30)) == [(t(9, 30), t(10))]


def test_sim_keeps_the_past_when_a_reservation_changes(net):
    """Before step 7C a modify recomputed the whole flow at the new rate; now it applies from its time on."""
    ctx = make_ctx(net)
    s = ctx.sense.propagate(intent(t(9), t(10), 40), now=t(9))
    net.start_flow(s.instance_id, t(9), 50 * TB)
    ctx.sense.modify(s.instance_id, intent(t(9), t(10), 20), now=t(9, 30))
    assert net.flow_trace(s.instance_id, t(10)).segments == [(t(9), t(9, 30), 40), (t(9, 30), t(10), 20)]
    ctx.sense.cancel(s.instance_id, now=t(9, 45))
    assert net.flow_trace(s.instance_id, t(10)).sent == pytest.approx(40e9 / 8 * 1800 + 20e9 / 8 * 900)


def test_switch_flow():
    net = make_net(0)
    ctx = make_ctx(net)
    a = ctx.sense.propagate(intent(t(9), t(10), 40), now=t(9))
    b = ctx.sense.propagate(intent(t(9), t(10), 20), now=t(9)).instance_id
    net.start_flow(a.instance_id, t(9), 9 * TB)
    net.switch_flow(a.instance_id, b, t(9, 15))                       # 4.5 TB sent, 4.5 TB left at 20
    assert net.flow_trace(a.instance_id, t(11)).sent == 4.5 * TB
    assert net.flow_trace(b, t(11)).finished_at == t(9, 15) + sec(4.5 * TB * 8 / 20e9)
