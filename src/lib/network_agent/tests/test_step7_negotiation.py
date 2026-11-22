"""Workflow-changing repairs require approval; autonomous repairs preserve the existing promise."""

from copy import deepcopy
from datetime import timedelta

import pytest

from ..src.adapters.sense import SenseError
from ..src.models.schemas import RepairDecision
from ..src.runtime.repair import RulePolicy
from .helpers import (L1, L2, L4, TICK, book, make_committed_ctx, make_ctx, make_net, modify, runtime, t, tr)
from .test_step7_repair import tight, two_priorities


class Scheduler:
    def __init__(self, decide):
        self.decide = decide
        self.calls = []

    def choose(self, proposals, now):
        self.calls.append(proposals)
        return self.decide(proposals, now)


@pytest.fixture
def extension():
    net = make_net()
    ctx = make_committed_ctx(net)
    net.start_flow("si-1", t(9), 50 * 10**12)
    net.add_outage("L2", t(9, 30), t(9, 45))
    return net, ctx


def test_extend_does_not_mutate_before_approval(extension):
    _, ctx = extension
    before = ctx.commitments.copy()
    bookings = deepcopy(ctx.ledger._bookings)

    def approve(proposals, now):
        assert ctx.commitments == before and ctx.ledger._bookings == bookings
        [proposal] = proposals
        assert proposal.kind == "extend" and len(proposal.changes) == 1
        change = proposal.changes[0]
        assert change.rate_profile_after[0].end > change.commitment_before.rate_profile[0].end
        assert change.predicted_finish_after <= change.latest_finish
        return RepairDecision(proposal_id=proposal.proposal_id)

    ctx.repair_coordinator = Scheduler(approve)
    out = runtime(ctx, TICK, t(10))
    assert out["reports"]["link_down"][0].action == "extend"
    assert out["repair_proposals"] == ctx.repair_coordinator.calls[0]


@pytest.mark.parametrize("mode", ["missing", "reject", "none", "unknown", "unavailable"])
def test_extend_without_valid_approval_leaves_commitment_unchanged(extension, mode):
    _, ctx = extension
    before = ctx.commitments.copy()

    def decide(proposals, now):
        if mode == "unavailable":
            raise RuntimeError("scheduler unavailable")
        if mode == "none":
            return None
        return RepairDecision(proposal_id="not-offered" if mode == "unknown" else None)

    ctx.repair_coordinator = None if mode == "missing" else Scheduler(decide)
    out = runtime(ctx, TICK, t(10))
    assert ctx.commitments == before
    assert out["repair_results"][0].outcome == "unresolved"
    assert "scheduler" in out["repair_results"][0].tried[0]


def test_rejection_continues_to_increase_without_a_second_approval(extension):
    net, ctx = extension
    net._background[L2].clear()  # Free capacity is now available on MAIN.
    original_end = ctx.commitments["cmt-1"].rate_profile[-1].end
    ctx.repair_coordinator = Scheduler(lambda plans, now: RepairDecision(reason="keep downstream start",
                                                                         latest_finish=original_end))
    out = runtime(ctx, TICK, t(10))
    report = out["reports"]["link_down"][0]
    assert report.action == "increase" and report.predicted_finish_p95 <= original_end
    assert report.commitment.rate_profile[-1].end == original_end
    assert len(ctx.repair_coordinator.calls) == 1


@pytest.mark.parametrize("change", ["capacity", "commitment"])
def test_approval_revalidates_before_execution(extension, change):
    net, ctx = extension

    def decide(proposals, now):
        if change == "capacity":
            net.add_background(L2, t(12), t(15), 100)
        else:
            modify(ctx, "q1/T1/1", t(9), t(11, 30), 40, now=now)
        return RepairDecision(proposal_id=proposals[0].proposal_id)

    ctx.repair_coordinator = Scheduler(decide)
    out = runtime(ctx, TICK, t(10))
    assert out["repair_results"][0].outcome == "unresolved"
    expected = "no longer feasible" if change == "capacity" else "commitment changed"
    assert expected in out["repair_results"][0].tried[0]


def test_increase_must_keep_original_end_even_if_request_deadline_allows_more_time():
    net = make_net(50)
    ctx = make_ctx(net)
    si = book(ctx, "q1", tr("T", nbytes=18 * 10**12, window=(t(9), t(10, 10))), 2)
    original = ctx.commitments["cmt-1"]
    net.start_flow(si, t(9), 18 * 10**12)
    net.add_outage("L2", t(9, 15), t(9, 30))
    out = runtime(ctx, TICK, t(9, 40))
    assert out["repair_results"][0].outcome == "unresolved"
    assert ctx.commitments["cmt-1"] == original


class RateOnly(RulePolicy):
    def plan_local_repair(self, ctx, assessment, now):
        return ["increase"]


def test_unknown_slowdown_does_not_gain_rate_merely_because_capacity_is_free(extension):
    net, ctx = extension
    net.add_slowdown("si-1", t(9), t(15), 0.1)
    # Establish recent progress first; known link damage must not hide the throughput mismatch.
    runtime(ctx, TICK, t(10), policy=RateOnly())
    before = ctx.commitments.copy()
    out = runtime(ctx, TICK, t(10, 5), policy=RateOnly())
    assert "insufficient evidence" in out["repair_results"][0].tried[0]
    assert ctx.commitments == before


def test_reroute_confirms_handoff_before_cancelling_old_circuit(tight):
    net, ctx = tight
    controller = ctx.transfer_controller

    class CheckSwitch:
        def switch(self, old, new, now):
            assert ctx.sense.state(old).state == ctx.sense.state(new).state == "committed"
            assert ctx.commitments["cmt-1"].circuit_id == old
            return controller.switch(old, new, now)

    ctx.transfer_controller = CheckSwitch()
    out = runtime(ctx, TICK, t(10))
    assert out["reports"]["congestion"][0].action == "reroute"
    assert net._flows["si-1"].stop == t(10) and "si-2" in net._flows
    assert ctx.sense.state("si-1").state == "cancelled"


@pytest.mark.parametrize("mode", ["reject", "exception", "missing"])
def test_unconfirmed_handoff_preserves_old_circuit_and_returns_new_capacity(tight, mode):
    _, ctx = tight
    before = ctx.commitments.copy()

    class FailedSwitch:
        def switch(self, old, new, now):
            if mode == "exception":
                raise RuntimeError("switch failed without moving the transfer")
            return False

    ctx.transfer_controller = None if mode == "missing" else FailedSwitch()
    out = runtime(ctx, TICK, t(10))
    assert out["repair_results"][0].outcome == "unresolved"
    assert ctx.commitments == before and ctx.sense.state("si-1").state == "committed"
    slot = ctx.ledger.slots_covering(t(10), t(11))[0]
    assert ctx.ledger.own(L4, slot) == 0


def test_reroute_cooldown_blocks_repeated_switches(tight):
    _, ctx = tight
    ctx.last_reroute["cmt-1"] = t(10) - timedelta(seconds=1)
    out = runtime(ctx, TICK, t(10))
    assert "cooldown" in out["repair_results"][0].tried[-1]
    assert ctx.commitments["cmt-1"].circuit_id == "si-1"


def test_reroute_does_not_keep_a_shared_damaged_hop(tight):
    net, ctx = tight
    net.add_background(L1, t(9, 30), t(12), 90)
    out = runtime(ctx, TICK, t(10))
    assert out["repair_results"][0].outcome == "unresolved"
    assert list(ctx.sense._states) == ["si-1"]


@pytest.mark.parametrize("accept", [False, True])
def test_borrow_proposes_complete_plans_without_changing_live_allocations(two_priorities, accept):
    _, ctx, *_ = two_priorities()
    original = ctx.commitments.copy()
    bookings = deepcopy(ctx.ledger._bookings)

    def decide(plans, now):
        assert ctx.commitments == original and ctx.ledger._bookings == bookings
        assert all(plan.kind == "borrow" for plan in plans)
        for plan in plans:
            assert {c.commitment_before.commitment_id for c in plan.changes} == {"cmt-1", "cmt-2"}
            assert all(c.predicted_finish_after <= c.latest_finish for c in plan.changes)
        # Exercise selection of a different complete candidate, not always the first one.
        return RepairDecision(proposal_id=plans[-1].proposal_id if accept else None)

    ctx.repair_coordinator = Scheduler(decide)
    out = runtime(ctx, TICK, t(9, 20))
    assert ctx.repair_coordinator.calls
    if accept:
        chosen = ctx.repair_coordinator.calls[-1][-1]
        for change in chosen.changes:
            assert ctx.commitments[change.commitment_before.commitment_id].rate_profile == change.rate_profile_after
    else:
        assert ctx.commitments == original and ctx.ledger._bookings == bookings
        assert out["repair_results"][0].outcome == "unresolved"


def test_borrow_rolls_back_approved_lenders_if_target_execution_fails(two_priorities, monkeypatch):
    _, ctx, high, low = two_priorities()
    original = ctx.commitments.copy()
    real_modify = ctx.sense.modify

    def fail_target(instance, intent, now):
        if instance == high:
            raise SenseError("modify", "injected")
        return real_modify(instance, intent, now)

    monkeypatch.setattr(ctx.sense, "modify", fail_target)
    out = runtime(ctx, TICK, t(9, 20))
    assert ctx.commitments == original
    assert out["repair_results"][0].outcome == "unresolved"
    assert "approved borrow execution failed" in out["repair_results"][0].tried[-1]


def test_borrow_plan_can_require_two_lenders_together():
    net = make_net(20)
    net.add_background(L4, t(9), t(12), 40)
    ctx = make_ctx(net)
    first = book(ctx, "qL1", tr("L1", nbytes=18 * 10**12, window=(t(9, 30), t(17)), priority=1), 1)
    modify(ctx, "qL1/L1/1", t(9, 30), t(10, 30), 40)
    second = book(ctx, "qL2", tr("L2", nbytes=18 * 10**12, window=(t(9, 30), t(17)), priority=1), 1)
    high = book(ctx, "qH", tr("H", nbytes=9 * 10**12, window=(t(9), t(10, 10)), priority=2), 2)
    for instance in (first, second):
        net.start_flow(instance, t(9, 30), 18 * 10**12)
    net.start_flow(high, t(9), 9 * 10**12)
    net.add_background(L2, t(9, 10), t(9, 30), 60)

    def choose(plans, now):
        assert all(len(plan.changes) == 3 for plan in plans)
        assert {c.commitment_before.commitment_id for c in plans[0].changes} == {"cmt-1", "cmt-2", "cmt-3"}
        return RepairDecision(proposal_id=plans[0].proposal_id)

    ctx.repair_coordinator = Scheduler(choose)
    out = runtime(ctx, TICK, t(9, 20))
    assert len(ctx.repair_coordinator.calls) == 1
    assert len(out["reports"]["congestion"]) == 3
    assert sum(report.action == "lend" for report in out["reports"]["congestion"]) == 2


def test_borrow_rechecks_capacity_after_approval(two_priorities):
    net, ctx, *_ = two_priorities()
    original = ctx.commitments.copy()

    def decide(plans, now):
        net.add_background(L2, t(9, 30), t(17), 80)
        return RepairDecision(proposal_id=plans[0].proposal_id)

    ctx.repair_coordinator = Scheduler(decide)
    out = runtime(ctx, TICK, t(9, 20))
    assert ctx.commitments == original
    assert "no longer feasible" in out["repair_results"][0].tried[-1]


def test_borrow_reports_a_lender_that_cannot_be_rolled_back(two_priorities, monkeypatch):
    _, ctx, high, low = two_priorities()
    real_modify = ctx.sense.modify
    changed_lender = False

    def fail_target_and_rollback(instance, intent, now):
        nonlocal changed_lender
        if instance == high or (instance == low and changed_lender):
            raise SenseError("modify", "injected")
        changed_lender = True
        return real_modify(instance, intent, now)

    monkeypatch.setattr(ctx.sense, "modify", fail_target_and_rollback)
    out = runtime(ctx, TICK, t(9, 20))
    by_id = {report.commitment_id: report for report in out["reports"]["congestion"]}
    assert by_id["cmt-2"].outcome == "unresolved"
    assert by_id["cmt-1"].action == "lend"
    assert by_id["cmt-1"].commitment == ctx.commitments["cmt-1"]
    assert "rollback failed" in out["repair_results"][-1].tried[-1]
