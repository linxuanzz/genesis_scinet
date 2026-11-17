"""Graph B · Runtime Graph (step 7): after commit, find deviations from what we promised, judge them,
repair locally where possible, and report to the scheduling agent.

    START(event) → deduplicate_event ─ duplicate ─► END
                     │ new alert / Tick
                     ▼
                   classify_event ─ no deviation ─► remember_event → END
                     │ deviation
                     ▼
                   scan_path → ◇ triage ─ all finish (or retry deferred) ─► remember_event → END
                                 │ some do not
                                 ▼
                               ◇ plan_local_repair ─ nothing worth trying ─► report_deviation (unresolved)
                                 │ candidates
                                 ▼
                               execute_repair ─► report_deviation (repaired / unresolved) → remember_event → END

    deduplicate_event validate the event and discard recently processed identical alerts; always pass ticks
    classify_event    R1: refresh what the event concerns, find the commitments that deviate and why
                      (deviation.py)
    scan_path         R2: add the commitments on hops found damaged that the event did not concern; for
                      each, the remaining bytes, the rate expected from now on and p50 / p95 (forecast.py)
    triage            R3: does the commitment still finish inside its reservation (repair.py, a policy)
    plan_local_repair which repairs to try, smallest change first; higher priority first (a policy)
    execute_repair    extend / raise_rate / reroute / borrow, each rolled back on failure (repair.py,
                      with graph A's operations)
    report_deviation  one DeviationReport per commitment repaired or unresolved, grouped by cause
    remember_event    cache the alert only after successful processing; failed runs remain retryable

The event is a ``Tick`` (periodic fallback) or a ``TelemetryAlert`` (link_down / link_up,
link_capacity_below, flow_below_rate, flow_finished / flow_stalled); both are provisional schemas. It may
come as a model or as the JSON dict telemetry sent. A malformed event is not dropped: it is treated as a
tick, so whatever it was about still gets checked, and the reason is kept in ``invalid_event``.

The reports are the graph's output (``reports``); sending them to the scheduling agent is the caller's
job (a push channel is a hook). The two policy nodes run ``RulePolicy`` unless build_runtime_graph is
given another. Graph B shares the AgentContext of graph A; as there, nodes only orchestrate.
"""

from datetime import datetime, timedelta
from functools import partial
from typing import TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError

from ...context.context import AgentContext, AlertKey, RepairConditions
from ...models.schemas import RUNTIME_EVENT, Cause, DeviationReport, TelemetryAlert, Tick
from ...runtime.deviation import Deviation, find_deviations_for_event, find_deviations_on_damaged_hops
from ...runtime.forecast import Assessment, assess_all
from ...runtime.repair import (NOTHING_TO_TRY, RepairPlan, RepairResult, RulePolicy, RuntimePolicy, execute, plan_all,
                               forget_changed_commitments, report, triage_all, unresolved_result)


class RuntimeState(TypedDict, total=False):
    event: dict | Tick | TelemetryAlert           # input: what started this run
    now: datetime                                 # input: current time
    parsed: Tick | TelemetryAlert                 # written by deduplicate_event; malformed events become ticks
    invalid_event: str                            # written by deduplicate_event when the event was malformed
    event_key: AlertKey | None
    duplicate_event: bool
    checked: list[str]                            # written by classify_event, added to by scan_path: commitments seen
    refreshed: list[str]                          # written by classify_event, added to by scan_path: links pulled
    deviations: list[Deviation]                   # written by classify_event, added to by scan_path
    assessments: list[Assessment]                 # written by scan_path: one per deviation
    finishes_in_reservation: list[str]            # written by triage: nothing to do
    retry_deferred: list[str]                     # written by triage: unchanged failure, retry not yet due
    repair_conditions: dict[str, RepairConditions]  # pre-repair snapshot, saved only on failure
    to_repair: list[Assessment]                   # written by triage
    plans: list[RepairPlan]                       # written by plan_local_repair: those with something to try
    repair_results: list[RepairResult]            # written by plan_local_repair (nothing to try), added to by
                                                  # execute_repair
    reports: dict[Cause, list[DeviationReport]]   # output, written by report_deviation


# ── nodes ────────────────────────────────────────────────────────────────

def deduplicate_event(state: RuntimeState, runtime: Runtime[AgentContext]) -> dict:
    """Drop recent successful alert duplicates before any telemetry or flow reads; ticks always pass.

    A different delivery id or observation timestamp alone is not a new condition. The fixed cache
    lifetime allows reassessment even without ticks and is not extended by duplicate deliveries.
    """
    ctx, now = runtime.context, state["now"]
    for key, expires_at in list(ctx.processed_alerts.items()):
        if expires_at <= now:
            del ctx.processed_alerts[key]
    out: dict = {}
    try:
        event = RUNTIME_EVENT.validate_python(state["event"])
    except ValidationError as e:
        event = Tick()
        out["invalid_event"] = "; ".join(err["msg"] for err in e.errors())
    key = (AlertKey(event.source, event.kind, event.link_id, event.flow_id, event.start, event.end,
                    event.measured_gbps) if isinstance(event, TelemetryAlert) else None)
    return out | {"parsed": event, "event_key": key, "duplicate_event": key in ctx.processed_alerts}


def classify_event(state: RuntimeState, runtime: Runtime[AgentContext]) -> dict:
    """R1: refresh what the event concerns and find the commitments that deviate, with their cause."""
    forget_changed_commitments(runtime.context)
    found = find_deviations_for_event(runtime.context, state["parsed"], state["now"])
    return {"checked": found.checked, "refreshed": found.refreshed, "deviations": found.deviations}


def remember_event(state: RuntimeState, runtime: Runtime[AgentContext]) -> dict:
    """Only completed runs enter the cache. Graph invocations sharing a context run sequentially."""
    if state["event_key"] is not None:
        runtime.context.processed_alerts[state["event_key"]] = (
            state["now"] + timedelta(seconds=runtime.context.cfg.event_dedup_seconds))
    return {}


def scan_path(state: RuntimeState, runtime: Runtime[AgentContext]) -> dict:
    """R2: widen to the commitments on damaged hops, then assess every deviation."""
    ctx, now = runtime.context, state["now"]
    more = find_deviations_on_damaged_hops(ctx, state["deviations"], state["checked"], now)
    deviations = state["deviations"] + more.deviations
    assessments, refreshed = assess_all(ctx, deviations, now)
    return {"deviations": deviations, "checked": state["checked"] + more.checked, "assessments": assessments,
            "refreshed": sorted(set(state["refreshed"]) | set(more.refreshed) | set(refreshed))}


def triage(state: RuntimeState, runtime: Runtime[AgentContext], policy: RuntimePolicy) -> dict:
    """R3 (policy): finishes_in_reservation, retry deferred, or to repair."""
    triaged = triage_all(runtime.context, policy, state["assessments"], state["now"])
    return {"finishes_in_reservation": triaged.finishes_in_reservation, "retry_deferred": triaged.retry_deferred,
            "to_repair": triaged.to_repair, "repair_conditions": triaged.conditions,
            "refreshed": sorted(set(state["refreshed"]) | set(triaged.refreshed))}


def plan_local_repair(state: RuntimeState, runtime: Runtime[AgentContext], policy: RuntimePolicy) -> dict:
    """(policy) Which repairs to try for each commitment, highest priority first; none worth trying → unresolved."""
    plans = plan_all(runtime.context, policy, state["to_repair"], state["now"])
    return {"plans": [p for p in plans if p.steps],
            "repair_results": [unresolved_result(p.assessment, (NOTHING_TO_TRY,)) for p in plans if not p.steps]}


def execute_repair(state: RuntimeState, runtime: Runtime[AgentContext]) -> dict:
    """Try the planned repairs; a commitment none of them repairs is unresolved."""
    return {"repair_results": state["repair_results"] + execute(runtime.context, state["plans"], state["now"])}


def report_deviation(state: RuntimeState, runtime: Runtime[AgentContext]) -> dict:
    """Report changed outcomes; remember failures separately for retry control."""
    return {"reports": report(runtime.context, state["repair_results"], state["repair_conditions"], state["now"])}


# ── edges ────────────────────────────────────────────────────────────────

def after_deduplicate(state: RuntimeState) -> str:
    return END if state["duplicate_event"] else "classify_event"


def after_classify(state: RuntimeState) -> str:
    return "scan_path" if state["deviations"] else "remember_event"


def after_triage(state: RuntimeState) -> str:
    return "plan_local_repair" if state["to_repair"] else "remember_event"


def after_plan(state: RuntimeState) -> str:
    return "execute_repair" if state["plans"] else "report_deviation"


# ── graph ────────────────────────────────────────────────────────────────

def build_runtime_graph(policy: RuntimePolicy | None = None):
    """Graph B; the two policy nodes run ``policy`` (RulePolicy if None)."""
    policy = policy or RulePolicy()
    g = StateGraph(RuntimeState, context_schema=AgentContext)
    g.add_node("deduplicate_event", deduplicate_event)
    g.add_node("classify_event", classify_event)
    g.add_node("scan_path", scan_path)
    g.add_node("triage", partial(triage, policy=policy))
    g.add_node("plan_local_repair", partial(plan_local_repair, policy=policy))
    g.add_node("execute_repair", execute_repair)
    g.add_node("report_deviation", report_deviation)
    g.add_node("remember_event", remember_event)
    g.add_edge(START, "deduplicate_event")
    g.add_conditional_edges("deduplicate_event", after_deduplicate, ["classify_event", END])
    g.add_conditional_edges("classify_event", after_classify, ["scan_path", "remember_event"])
    g.add_edge("scan_path", "triage")
    g.add_conditional_edges("triage", after_triage, ["plan_local_repair", "remember_event"])
    g.add_conditional_edges("plan_local_repair", after_plan, ["execute_repair", "report_deviation"])
    g.add_edge("execute_repair", "report_deviation")
    g.add_edge("report_deviation", "remember_event")
    g.add_edge("remember_event", END)
    return g.compile()
