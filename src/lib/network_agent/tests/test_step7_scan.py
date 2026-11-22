"""Step 7 B: graph B's scan_path, triage and report_deviation: what each deviation can expect from now on,
whether its reservation still covers it, and the DeviationReport sent when it does not.

Unless a test says otherwise, the agent has committed cmt-1 = q1/T1/1 on si-1: 09:00–11:46:40 @ 40 Gbps
along MAIN (L2 has 40 left before 12:00), latest_finish 15:00, and the WMS starts its 50 TB at 09:00.
40 Gbps for an hour moves 18 TB.
"""

from datetime import timedelta

import pytest
from pydantic import ValidationError

from ..src.models.schemas import DeviationReport, RateSegment, TelemetryAlert
from ..src.planning.estimate import IdealRateModel
from ..src.runtime.assessment import expected_gbps, expected_rates_under_reservation
from ..src.runtime.repair import NOTHING_TO_TRY, RulePolicy
from .helpers import (L2, MAIN, TICK, book, make_committed_ctx, make_ctx, make_net, modify, reports, runtime, t, tr,
                      visited)

TB = 10**12


@pytest.fixture
def net():
    return make_net()


@pytest.fixture
def ctx(net):
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * TB)
    return ctx


def only(out):
    [a] = out["assessments"]
    return a


class NoRepair(RulePolicy):
    """Plans nothing, so the ledger stays as scan_path read it."""

    def plan_local_repair(self, ctx, assessment, now):
        return []


def scanned(ctx, now):
    """Run graph B without repairing; returns the final state."""
    return runtime(ctx, TICK, now, policy=NoRepair())


# ── assessment ──────────────────────────────────────────────────────────────

def test_outage_in_expected_rates(net, ctx):
    """15 minutes lost at 09:30: 36.5 TB left at 10:00, which the circuit, kept at 40, moves by 12:01:40."""
    net.add_outage("L2", t(9, 30), t(9, 45))
    a = only(scanned(ctx, t(10)))
    assert (a.remaining_bytes, a.deadline, a.cap_gbps) == (36.5 * TB, t(15), None)
    assert a.finish is None and not a.finishes_in_reservation       # not through by 11:46:40
    assert a.finish_if_kept == (t(12, 1) + timedelta(seconds=40),) * 2


def test_congestion_ahead_is_in_the_expected_rates(net, ctx):
    """L2 has 20 more Gbps of background until 10:30: our 40 gets 20 there, then 40 again."""
    net.add_background(L2, t(9, 30), t(10, 30), 20)
    out = scanned(ctx, t(10))
    reserved_offer = out["deviations"][0].committed.reserved_offer
    end = reserved_offer.placement.end
    spans = expected_rates_under_reservation(ctx.ledger, reserved_offer, t(10), None)
    assert spans == [(t(10), t(10, 30), 20), (t(10, 30), end, 40)]
    assert only(out).finish_if_kept[1] == t(12, 16) + timedelta(seconds=40)   # 30 min at half rate, twice


def test_planned_outage_ahead_reads_as_zero(net, ctx):
    net.add_outage("L3", t(11), t(11, 15))
    reserved_offer = scanned(ctx, t(10))["deviations"][0].committed.reserved_offer
    spans = expected_rates_under_reservation(ctx.ledger, reserved_offer, t(10), None)
    assert spans == [(t(10), t(11), 40), (t(11), t(11, 15), 0),
                     (t(11, 15), reserved_offer.placement.end, 40)]


def test_our_circuits_share_a_congested_hop_in_proportion():
    """60 and 20 booked on MAIN where L2 leaves 80; 40 more background leaves 40 for them: 30 and 10."""
    net = make_net(20)
    ctx = make_ctx(net)
    for booking_id, gbps in (("a", 60), ("b", 20)):
        ctx.ledger.pending(booking_id, MAIN, [RateSegment(start=t(9), end=t(11), gbps=gbps)])
    net.add_background(L2, t(9), t(11), 40)
    ctx.ledger.apply(ctx.telemetry.link_samples(list(MAIN), t(9), t(11), t(9)))
    i = ctx.ledger.slots_covering(t(9), t(9, 1))[0]
    assert [expected_gbps(ctx.ledger, MAIN, i, g, b) for b, g in (("a", 60), ("b", 20))] == [30, 10]
    assert expected_gbps(ctx.ledger, MAIN, i, 40, None) == 40 * 40 / 120                # a third circuit at 40


def test_unlocated_expected_rate_is_capped_by_the_rate_still_seen(net, ctx):
    """A slow source disk (0.6): no earlier reading, so the average since the start, 24 Gbps, caps the expected rate."""
    net.add_slowdown("si-1", t(9), t(15), 0.6)
    a = only(scanned(ctx, t(10)))
    assert a.deviation.cause == "unlocated" and a.cap_gbps == pytest.approx(24)
    assert a.finish_if_kept[1] == t(10) + timedelta(seconds=(50 - 10.8) * TB * 8 / 24e9)


def test_unlocated_but_recovered(net, ctx):
    """Slow until 09:30 only. At 09:50 the average since the start (28 Gbps) still caps the expected rate; at
    10:00 the rate since 09:50 is back to 40, so nothing does."""
    net.add_slowdown("si-1", t(9), t(9, 30), 0.5)
    assert only(scanned(ctx, t(9, 50))).cap_gbps == pytest.approx(28)
    a = only(scanned(ctx, t(10)))
    assert a.deviation.recent_gbps == pytest.approx(40) and a.cap_gbps is None


def test_cautious_rate_model_is_used(net, ctx):
    """The RateModel hook gives p95: a model 10 minutes more cautious makes graph B book up to its p95."""
    class Cautious(IdealRateModel):
        def finish_at_expected_rates(self, spans, nbytes):
            done = super().finish_at_expected_rates(spans, nbytes)
            return done and (done[0], done[1] + timedelta(minutes=10))
    ctx.rate_model = Cautious()
    net.add_outage("L2", t(9, 30), t(9, 45))
    [r] = runtime(ctx, TICK, t(10))["reports"]["link_down"]
    p50 = t(12, 1) + timedelta(seconds=40)
    assert (r.predicted_finish_p50, r.predicted_finish_p95) == (p50, p50 + timedelta(minutes=10))
    assert r.commitment.rate_profile[0].end == p50 + timedelta(minutes=10)


# ── triage ────────────────────────────────────────────────────────────────

def test_still_finishes_in_reservation_after_a_repair(net, ctx):
    """The congestion lasts until 10:30, so the next tick still sees damage ahead; the extended reservation
    covers it, and triage ends the run."""
    net.add_background(L2, t(9, 30), t(10, 30), 20)
    assert reports(runtime(ctx, TICK, t(10))) == [("cmt-1", "congestion", "repaired", "extend")]
    out = runtime(ctx, TICK, t(10, 5))
    assert out["finishes_in_reservation"] == ["cmt-1"] and "reports" not in out
    assert visited(ctx, TICK, t(10, 10)) == ["deduplicate_event", "update_forecast", "detect_deviations", "scan_path", "triage", "remember_event"]


def test_widen_to_other_commitments_on_a_damaged_hop():
    """A flow alert says si-1 gets 20 at 10:00: L2 is congested now (30 more Gbps of others' registered
    traffic from 09:55 to 12:30). cmt-2 (12:00 @ 100, not started) books L2 at 12:00, so scan_path
    checks it as well and finds the congestion ahead of it."""
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/1", "q1/T2/2")
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_background(L2, t(9, 55), t(12, 30), 30)
    alert = TelemetryAlert(alert_id="a1", kind="flow_below_rate", flow_id="si-1", start=t(9, 55), end=t(10),
                           measured_gbps=20, observed_at=t(10), source="mock")
    out = runtime(ctx, alert, t(10))
    assert out["checked"] == ["cmt-1", "cmt-2"]
    assert [(d.commitment_id, d.cause) for d in out["deviations"]] == [("cmt-1", "congestion"), ("cmt-2", "congestion")]


# ── unresolved and the reports ────────────────────────────────────────────

@pytest.fixture
def hopeless():
    """L2 down 09:30–10:30 and latest_finish 11:50: 41 TB left at 10:30 would need 68 Gbps, and no path
    gives that much (MAIN is at 40 before 12:00, ALT at 40)."""
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(11, 50))), 1)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(10, 30))
    return net, ctx


def test_unresolved_when_every_repair_fails(hopeless):
    _, ctx = hopeless
    out = runtime(ctx, TICK, t(10))
    [r] = out["reports"]["link_down"]
    assert (r.outcome, r.action, r.links, r.latest_finish) == ("unresolved", None, [L2], t(11, 50))
    assert r.commitment == ctx.commitments["cmt-1"]                              # left as it was
    assert r.predicted_finish_p95 > r.latest_finish
    [o] = out["repair_results"]
    assert [why.split(":")[0] for why in o.tried] == ["extend", "increase", "reroute"]
    assert ctx.reported_unresolved == {"cmt-1": r}


def test_nothing_worth_trying_goes_straight_to_the_report():
    """At 11:40, 7.5 minutes before the circuit ends and 10 before latest_finish, 15 TB are left: not even
    the full 100 Gbps of MAIN would make it, so no repair is tried."""
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(11, 50))), 1)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(10, 30))
    assert visited(ctx, TICK, t(11, 40)) == ["deduplicate_event", "update_forecast", "detect_deviations", "scan_path", "triage",
                                             "plan_local_repair", "report_deviation", "remember_event"]
    ctx.reported_unresolved.clear()
    ctx.failed_repairs.clear()
    [o] = runtime(ctx, TICK, t(11, 40))["repair_results"]
    assert o.tried == (NOTHING_TO_TRY,)


def test_an_unresolved_deviation_is_reported_once(hopeless):
    _, ctx = hopeless
    assert reports(runtime(ctx, TICK, t(10))) == [("cmt-1", "link_down", "unresolved", None)]
    again = runtime(ctx, TICK, t(10, 5))
    assert again["retry_deferred"] == ["cmt-1"] and "reports" not in again
    assert visited(ctx, TICK, t(10, 10)) == ["deduplicate_event", "update_forecast", "detect_deviations", "scan_path", "triage", "remember_event"]


def test_reported_again_once_the_cause_changes():
    """A changed rate cap updates the assessment; L2 going down under the slow transfer later changes the
    cause too (the slowness is now located on the current slot)."""
    net = make_net()
    ctx = make_ctx(net)
    book(ctx, "q1", tr("T1", window=(t(9), t(11, 50))), 1)
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_slowdown("si-1", t(9, 30), t(15), 0.0)
    assert reports(runtime(ctx, TICK, t(10))) == [("cmt-1", "unlocated", "unresolved", None)]
    stalled = runtime(ctx, TICK, t(10, 5))
    assert stalled["assessments"][0].cap_gbps == 0
    assert stalled["reports"]["unlocated"][0].predicted_finish_p95 is None
    net.add_outage("L2", t(10, 6), t(11, 15))
    assert reports(runtime(ctx, TICK, t(10, 10))) == [("cmt-1", "link_down", "unresolved", None)]


def test_the_scheduling_agent_decides_then_graph_b_forgets(hopeless):
    """The scheduling agent answers the report through graph A: it lets T1 run until 14:00."""
    _, ctx = hopeless
    runtime(ctx, TICK, t(10))
    reply = modify(ctx, "q1/T1/1", t(9), t(14), 40, reserve_id="rsv-1", now=t(10, 1))["response"]
    assert reply.commitment.rate_profile[0].end == t(14)
    out = runtime(ctx, TICK, t(10, 5))
    assert ctx.reported_unresolved == {} and out["finishes_in_reservation"] == ["cmt-1"]


def test_reports_are_grouped_by_cause():
    """cmt-1 (09:00 @ 40) loses 15 minutes to an outage; cmt-2 (12:00 @ 100, not started) has congestion
    ahead on L2 at 12:00."""
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/1", "q1/T2/2")
    net.start_flow("si-1", t(9), 50 * TB)
    net.add_outage("L2", t(9, 30), t(9, 45))
    net.add_background(L2, t(12), t(12, 15), 30)
    out = runtime(ctx, TICK, t(10))
    assert {cause: [r.commitment_id for r in rs] for cause, rs in out["reports"].items()} == {
        "link_down": ["cmt-1"], "congestion": ["cmt-2"]}


def test_a_replaced_policy(net, ctx):
    """The ◇ nodes run whatever policy graph B is built with: here one that never repairs."""
    class ReportOnly(RulePolicy):
        def plan_local_repair(self, ctx, assessment, now):
            return []
    net.add_outage("L2", t(9, 30), t(9, 45))
    assert reports(runtime(ctx, TICK, t(10), policy=ReportOnly())) == [("cmt-1", "link_down", "unresolved", None)]


# ── DeviationReport ───────────────────────────────────────────────────────

def report(**over):
    ctx = make_committed_ctx(make_net())
    base = dict(commitment_id="cmt-1", transfer_id="T1", workflow_id="WF-1", cause="congestion", links=[L2],
                outcome="repaired", action="extend", predicted_finish_p50=t(12), predicted_finish_p95=t(12),
                latest_finish=t(15), commitment=ctx.commitments["cmt-1"])
    return DeviationReport(**(base | over))


def test_a_good_report():
    assert report().outcome == "repaired"
    unresolved = report(outcome="unresolved", action=None, predicted_finish_p50=None, predicted_finish_p95=None)
    assert unresolved.action is None


@pytest.mark.parametrize("over", [
    {"action": None},                                             # repaired without its action
    {"outcome": "unresolved"},                                    # unresolved with one
    {"action": "lend"},                                           # lend without lent_to
    {"lent_to": "cmt-2"},                                         # lent_to without lend
    {"predicted_finish_p95": None},                               # only one of the two
    {"predicted_finish_p50": t(13)},                              # p50 after p95
    {"predicted_finish_p50": None, "predicted_finish_p95": None},  # repaired without a finish
    {"commitment_id": "cmt-9"},                                   # not the attached commitment
    {"cause": "slow"},
])
def test_bad_reports(over):
    with pytest.raises(ValidationError):
        report(**over)


def test_finish_along():
    m = IdealRateModel()
    spans = [(t(9), t(10), 40), (t(10), t(10, 30), 0), (t(10, 30), t(11), 40)]
    assert m.finish_at_expected_rates(spans, 18 * TB) == (t(10), t(10))
    assert m.finish_at_expected_rates(spans, 22.5 * TB) == (t(10, 45), t(10, 45))           # the outage is skipped over
    assert m.finish_at_expected_rates(spans, 30 * TB) is None
    assert m.finish_at_expected_rates([], TB) is None
