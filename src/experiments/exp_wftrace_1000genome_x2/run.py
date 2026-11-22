"""Exp3: two scaled 1000genome traces, end to end through the network agent (see docs/current_experiment_plan.md).

Builds the simulated network and the network agent from the config, places and scales the trace, runs the
co-simulation (src/lib/wftrace/cosim.py), and writes report.md, transfers.csv and tasks.csv into the run dir.
"""

import csv
from collections import Counter
from datetime import datetime, time, timezone
from pathlib import Path

from src.lib.network_agent.src.adapters.forecast_inputs import MockForecastInputs
from src.lib.network_agent.src.adapters.sense import MockSense
from src.lib.network_agent.src.adapters.telemetry import MockFlows, MockTelemetry
from src.lib.network_agent.src.adapters.transfer_controller import MockTransferController
from src.lib.network_agent.src.context.context import AgentContext
from src.lib.network_agent.src.models.config import load_config
from src.lib.network_agent.src.models.schemas import RepairDecision
from src.lib.network_agent.src.models.topology import Topology
from src.lib.network_agent.src.planning.estimate import IdealRateModel
from src.lib.network_agent.src.sim.sim import MockNetwork
from src.lib.network_agent.src.state.ledger import CapacityLedger
from src.lib.wftrace.cosim import CosimSettings, Cosimulation, WorkflowRun, records_of, reference_makespan
from src.lib.wftrace.trace import load_workflow, place

ROOT = Path(__file__).resolve().parents[3]


class ApproveFirst:
    """Scheduler stand-in for repair proposals (none are expected: nothing is injected)."""

    def choose(self, proposals, now):
        return RepairDecision(proposal_id=proposals[0].proposal_id)


def at(day: str, hhmm: str) -> datetime:
    return datetime.combine(datetime.fromisoformat(day).date(), time.fromisoformat(hhmm), tzinfo=timezone.utc)


def build(config: dict):
    day = config["day"]
    topology = Topology.from_dict(config["topology"])
    net = MockNetwork(topology)
    for b in config["background"]:
        net.add_background(b["link"], at(day, b["start"]), at(day, b["end"]), b["gbps"], registered=b["registered"])
    cfg = load_config(config)
    starts = [at(day, w["start"]) for w in config["workflows"]]
    ctx = AgentContext(cfg=cfg, topology=topology, ledger=CapacityLedger(topology, cfg, origin=min(starts)),
                       telemetry=MockTelemetry(net, validity_seconds=config["telemetry_validity_seconds"]),
                       sense=MockSense(net, vlan_range=tuple(config["sense_vlan_range"])), rate_model=IdealRateModel(),
                       flows=MockFlows(net), forecast_inputs=MockForecastInputs(net),
                       repair_coordinator=ApproveFirst(), transfer_controller=MockTransferController(net))
    workflow = load_workflow(ROOT / config["trace"])
    placement = place(workflow, config["program_sites"], config["data_site"])
    runs = [WorkflowRun(w["workflow_id"], workflow, placement, at(day, w["start"]), w["priority"],
                        config["data_scale"], config["compute_scale"]) for w in config["workflows"]]
    c = config["cosim"]
    settings = CosimSettings(c["step_seconds"], c["tick_seconds"], c["reserve_threshold_bytes"], c["reference_gbps"],
                             c["best_effort_gbps"], at(day, c["end"]))
    return net, ctx, runs, settings


def entry(config: dict, run_dir: Path) -> dict:
    net, ctx, runs, settings = build(config)
    result = Cosimulation(ctx, net, runs, settings).run()
    write_tables(result, run_dir)

    per_workflow = {}
    for run in runs:
        wf = run.workflow_id
        tasks = [t for t in result.tasks if t.workflow_id == wf]
        booked, best_effort = records_of(result.transfers, wf, True), records_of(result.transfers, wf, False)
        finished = [t.finished_at for t in tasks]
        makespan = (max(finished) - run.start).total_seconds() / 60 if all(finished) else None
        staged = [r.finished_at for r in booked if r.file in run.workflow.external_inputs]
        per_workflow[wf] = {
            "start": f"{run.start:%H:%M}",
            "tasks_done": sum(1 for f in finished if f),
            "tasks": len(tasks),
            "makespan_min": round(makespan, 1) if makespan else None,
            "compute_only_makespan_min": round(reference_makespan(run).total_seconds() / 60, 1),
            "inputs_staged_min": round((max(staged) - run.start).total_seconds() / 60, 1) if staged and all(staged) else None,
            "booked_transfers": len(booked),
            "booked_TB": round(sum(r.nbytes for r in booked) / 1e12, 2),
            "best_effort_transfers": len(best_effort),
            "best_effort_GB": round(sum(r.nbytes for r in best_effort) / 1e9, 2),
            "deadlines_met": sum(1 for r in booked if r.finished_at and r.finished_at <= r.latest_finish),
            "deadline_relaxed": sum(1 for r in booked if r.deadline_relaxed),
            "limited_by": dict(Counter(str(r.limited_by) for r in booked)),
            "mean_booked_gbps": round(sum(r.gbps for r in booked) / len(booked), 1) if booked else None,
            "mean_wait_to_start_min": round(sum((r.offer_start - r.ready_at).total_seconds() for r in booked)
                                            / len(booked) / 60, 2) if booked else None,
        }

    predicted = [r for r in result.transfers if r.booked and r.first_prediction]
    errors = [abs((r.first_prediction - r.ready_at).total_seconds()) for r in predicted]
    last_errors = [abs((r.last_prediction - r.ready_at).total_seconds()) for r in predicted]
    metrics = {
        "workflows": per_workflow,
        "runtime": {"ticks": result.ticks, "deviations": result.deviations, "reports": result.reports},
        "demand_forecast": {
            "booked_transfers_predicted_before_request": len(predicted),
            "booked_transfers": sum(1 for r in result.transfers if r.booked),
            "first_prediction_abs_error_s": {"mean": round(sum(errors) / len(errors), 1), "max": round(max(errors), 1)} if errors else None,
            "last_prediction_abs_error_s": {"mean": round(sum(last_errors) / len(last_errors), 1), "max": round(max(last_errors), 1)} if last_errors else None,
            "would_not_fit_reports": len(result.would_not_fit),
        },
    }
    write_report(metrics, result, run_dir)

    a, b = per_workflow["WF-A"], per_workflow["WF-B"]
    booked_all = [r for r in result.transfers if r.booked]
    h1 = (all(r.finished_at and r.finished_at <= r.latest_finish for r in booked_all)
          and result.deviations == 0 and a["tasks_done"] == a["tasks"] and b["tasks_done"] == b["tasks"])
    h2 = (b["limited_by"].get("own_commitment", 0) > 0 or (b["inputs_staged_min"] or 0) > (a["inputs_staged_min"] or 0))
    h3 = any(r.workflow_id == "WF-B" and r.first_prediction for r in booked_all)
    conclusion = (f"H1 {'成立' if h1 else '不成立'}:{len(booked_all)} 个预约传输,"
                  f"截止时间满足 {a['deadlines_met'] + b['deadlines_met']},巡检偏离 {result.deviations};"
                  f"H2 {'成立' if h2 else '不成立'}:数据准备 WF-A {a['inputs_staged_min']} min / WF-B {b['inputs_staged_min']} min;"
                  f"H3 {'有预报' if h3 else '无预报'}:首次预报的请求时间误差 {metrics['demand_forecast']['first_prediction_abs_error_s']}")
    return {"metrics": metrics, "conclusion": conclusion, "verdict": "✅" if h1 and h2 and h3 else "🔍"}


def write_tables(result, run_dir: Path) -> None:
    fields = ["workflow_id", "transfer_id", "file", "src", "dst", "nbytes", "booked", "ready_at", "latest_finish",
              "offer_start", "offer_end", "gbps", "path", "limited_by", "offers", "deadline_relaxed", "finished_at",
              "first_prediction", "last_prediction"]
    with open(run_dir / "transfers.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for r in sorted(result.transfers, key=lambda r: (r.ready_at, r.workflow_id, r.file)):
            row = {k: getattr(r, k) for k in fields}
            row["path"] = " ".join(link.split(":")[0] for link in r.path)
            writer.writerow(row)
    with open(run_dir / "tasks.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["workflow_id", "task_id", "site", "started_at", "finished_at"])
        for t in sorted(result.tasks, key=lambda t: (t.workflow_id, t.started_at or datetime.max.replace(tzinfo=timezone.utc))):
            writer.writerow([t.workflow_id, t.task_id, t.site, t.started_at, t.finished_at])


def write_report(metrics: dict, result, run_dir: Path) -> None:
    def hm(moment):
        return f"{moment:%H:%M:%S}" if moment else "—"

    lines = ["# Exp3 · two 1000genome workflows through the network agent", "",
             "## Per workflow", "", "| | WF-A | WF-B |", "|---|---|---|"]
    a, b = metrics["workflows"]["WF-A"], metrics["workflows"]["WF-B"]
    for key in a:
        lines.append(f"| {key} | {a[key]} | {b[key]} |")
    lines += ["", f"Runtime (graph B): {metrics['runtime']}", "", f"Demand forecast (part B): {metrics['demand_forecast']}",
              "", "## Booked transfers", "",
              "| WF | file | → | TB | ready | deadline | reserved | Gbps | path | limited_by | finished | first forecast |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted((r for r in result.transfers if r.booked), key=lambda r: (r.ready_at, r.workflow_id)):
        path = " ".join(link.split(":")[0] for link in r.path)
        lines.append(f"| {r.workflow_id} | {r.file[:40]} | {r.dst} | {r.nbytes / 1e12:.2f} | {hm(r.ready_at)} | "
                     f"{hm(r.latest_finish)} | {hm(r.offer_start)}–{hm(r.offer_end)} | {r.gbps:g} | {path} | "
                     f"{r.limited_by} | {hm(r.finished_at)} | {hm(r.first_prediction)} |")
    lines += ["", "## Graph B findings (no events injected)", ""] + [f"- {f}" for f in result.runtime_findings or ["none"]]
    (run_dir / "report.md").write_text("\n".join(lines) + "\n")
