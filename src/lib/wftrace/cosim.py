"""Co-simulation: workflows from traces, a mock scheduling agent, a mock WMS, and the network agent.

Time advances in fixed steps. At each step:

    1. transfers that have finished deliver their file at the destination site
    2. tasks that have finished make their outputs available at their site; each output needed at another
       site becomes a transfer
    3. tasks whose inputs are all at their site start, and run for their (scaled) runtime
    4. new transfers are requested: a large one goes through graph A (query → pick the offer that finishes
       first → reserve → commit) and then runs on the simulated network from the offer's start; a small one
       goes best effort at a fixed rate, without the ledger
    5. on every tick, graph B runs once (no events are injected), and the network agent's forecast part B
       asks this scheduling agent what it expects to request

The mock scheduling agent is the ``SciNetDemandSource``: it expects each large transfer not requested yet
at the time a reference schedule says its file will be ready (known times where they are known, otherwise
estimated: large transfers at the reference rate, small ones at the best-effort rate, tasks at their runtime).
A request's deadline is its ready time + bytes / reference rate: the slowest average rate the workflow
accepts.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.lib.network_agent.src.context.context import AgentContext
from src.lib.network_agent.src.graphs.protocol.protocol import build_protocol_graph
from src.lib.network_agent.src.graphs.runtime.runtime import build_runtime_graph
from src.lib.network_agent.src.models.schemas import (CommitRequest, QueryRequest, ReserveRequest, TimeWindow, Tick,
                                                TransferRequest)
from src.lib.network_agent.src.runtime.forecast import forecast_scinet_demand
from src.lib.network_agent.src.sim.sim import MockNetwork
from src.lib.wftrace.trace import FileTransfer, Placement, Workflow


@dataclass(frozen=True)
class CosimSettings:
    step_seconds: int                                 # time step of the loop
    tick_seconds: int                                 # graph B and the demand forecast run this often
    reserve_threshold_bytes: int                      # transfers at least this large are booked through graph A
    reference_gbps: float                             # deadline = ready + bytes / this
    best_effort_gbps: float                           # rate of a transfer that is not booked
    end: datetime                                     # stop here even if something is unfinished


@dataclass
class WorkflowRun:
    """One instance of a traced workflow: where it runs, when it starts, how much it is scaled."""

    workflow_id: str
    workflow: Workflow
    placement: Placement
    start: datetime
    priority: int
    data_scale: float
    compute_scale: float

    def nbytes(self, file: str) -> int:
        return int(self.workflow.file_bytes[file] * self.data_scale)

    def runtime(self, task_id: str) -> timedelta:
        return timedelta(seconds=self.workflow.tasks[task_id].runtime_seconds * self.compute_scale)


@dataclass
class TransferRecord:
    workflow_id: str
    file: str
    src: str
    dst: str
    nbytes: int
    booked: bool                                      # through graph A; otherwise best effort
    ready_at: datetime                                # when the file was ready and the transfer requested
    latest_finish: datetime
    transfer_id: str
    offer_start: datetime | None = None
    offer_end: datetime | None = None
    gbps: float | None = None
    path: tuple[str, ...] = ()
    limited_by: str | None = None                     # of the offer taken
    offers: int = 0
    deadline_relaxed: bool = False                    # no offer met the deadline: asked again without it
    instance_id: str | None = None
    finished_at: datetime | None = None
    first_prediction: datetime | None = None          # the earliest forecast of ready_at (part B)
    last_prediction: datetime | None = None           # the last forecast before it was requested


@dataclass
class TaskRecord:
    workflow_id: str
    task_id: str
    site: str
    started_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class CosimResult:
    transfers: list[TransferRecord]
    tasks: list[TaskRecord]
    ticks: int
    deviations: int
    reports: int
    would_not_fit: list[tuple[datetime, str]]         # (when, transfer id) the demand forecast said would not fit
    runtime_findings: list[str]                       # one line per deviation and report of graph B


def transfer_key(workflow_id: str, transfer: FileTransfer) -> str:
    return f"{workflow_id}:{transfer.file}>{transfer.dst_site}"


class MockSchedulingAgent:
    """Requests transfers as files become ready, and forecasts the ones it will request (SciNetDemandSource)."""

    def __init__(self, ctx: AgentContext, runs: list[WorkflowRun], settings: CosimSettings):
        self.ctx, self.runs, self.settings = ctx, runs, settings
        self.graph = build_protocol_graph()
        self.records: dict[str, TransferRecord] = {}  # transfer id → record, once requested
        self.cosim: "Cosimulation | None" = None      # set by the co-simulation, for the known state
        self._seq = 0

    def deadline(self, ready: datetime, nbytes: int) -> datetime:
        return ready + timedelta(seconds=nbytes * 8 / (self.settings.reference_gbps * 1e9))

    # ── SciNetDemandSource ────────────────────────────────────────────────

    def future_demand(self, now: datetime, until: datetime) -> list[TransferRequest]:
        expected = []
        for run in self.runs:
            ready = self.cosim.expected_ready(run, now)
            for transfer in run.placement.transfers:
                key = transfer_key(run.workflow_id, transfer)
                nbytes = run.nbytes(transfer.file)
                if key in self.records or nbytes < self.settings.reserve_threshold_bytes or ready[key] >= until:
                    continue
                expected.append(self.request(run, transfer, ready[key]))
        return expected

    # ── requests ──────────────────────────────────────────────────────────

    def request(self, run: WorkflowRun, transfer: FileTransfer, ready: datetime,
                latest: datetime | None = None) -> TransferRequest:
        nbytes = run.nbytes(transfer.file)
        return TransferRequest(id=transfer_key(run.workflow_id, transfer), workflow_id=run.workflow_id,
                               priority=run.priority, src=transfer.src_site, dst=transfer.dst_site, bytes=nbytes,
                               is_estimate=False, divisible=False,
                               window=TimeWindow(earliest_start=ready, latest_finish=latest or self.deadline(ready, nbytes)))

    def book(self, run: WorkflowRun, transfer: FileTransfer, now: datetime, net: MockNetwork) -> TransferRecord:
        """Query, take the offer that finishes first, reserve and commit it, start the flow."""
        request = self.request(run, transfer, now)
        record = TransferRecord(run.workflow_id, transfer.file, transfer.src_site, transfer.dst_site, request.bytes,
                                True, now, request.window.latest_finish, request.id)
        offers, query_id = self._query(request, now)
        if not offers:                                # nothing meets the deadline: ask again without one
            record.deadline_relaxed = True
            offers, query_id = self._query(self.request(run, transfer, now, self.settings.end), now)
        if not offers:
            raise RuntimeError(f"no offer at all for {request.id}")
        offer = min(offers, key=lambda o: (o.predicted_finish_p95, o.rate_profile[0].start))
        reserve_id = self._send("reserve", ReserveRequest(request_id=self._id("r"), query_id=query_id,
                                                          offer_ids=[offer.offer_id]), now).reserve_id
        commitment = self._send("commit", CommitRequest(request_id=self._id("c"), reserve_id=reserve_id), now).commitments[0]
        placement = self.ctx.reservations[reserve_id].reserved_offers[0].placement
        segment = offer.rate_profile[0]
        record.offer_start, record.offer_end, record.gbps = segment.start, segment.end, segment.gbps
        record.path, record.limited_by, record.offers = placement.path, offer.limited_by, len(offers)
        record.instance_id = commitment.circuit_id
        net.start_flow(commitment.circuit_id, segment.start, request.bytes)
        self.records[request.id] = record
        return record

    def _query(self, request: TransferRequest, now: datetime):
        query_id = self._id("q")
        response = self._send("query", QueryRequest(query_id=query_id, bundle=[request], mode="all_or_nothing"), now)
        [result] = response.results
        return (result.offers if result.status == "feasible" else []), query_id

    def _send(self, verb: str, message, now: datetime):
        response = self.graph.invoke({"verb": verb, "raw": message.model_dump(), "now": now}, context=self.ctx)["response"]
        if response.__class__.__name__ == "ErrorResponse":
            raise RuntimeError(f"{verb} failed: {response.code} {response.detail}")
        return response

    def _id(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq}"


@dataclass
class Cosimulation:
    ctx: AgentContext
    net: MockNetwork
    runs: list[WorkflowRun]
    settings: CosimSettings
    scheduler: MockSchedulingAgent = field(init=False)
    tasks: dict[tuple[str, str], TaskRecord] = field(init=False, default_factory=dict)
    present: dict[tuple[str, str], dict[str, datetime]] = field(init=False, default_factory=dict)  # (wf, site) → file → since
    best_effort: list[TransferRecord] = field(init=False, default_factory=list)
    predictions: dict[str, list[datetime]] = field(init=False, default_factory=dict)  # transfer id → forecast ready times

    def __post_init__(self):
        self.scheduler = MockSchedulingAgent(self.ctx, self.runs, self.settings)
        self.scheduler.cosim = self
        self.ctx.scinet_demand = self.scheduler
        for run in self.runs:
            for task_id, site in run.placement.task_site.items():
                self.tasks[(run.workflow_id, task_id)] = TaskRecord(run.workflow_id, task_id, site)

    # ── what is known, and what is expected (for the demand forecast) ─────

    def expected_ready(self, run: WorkflowRun, now: datetime) -> dict[str, datetime]:
        """For each cross-site transfer of the run: when its file is (expected to be) ready to send. Known
        times where known; otherwise a reference schedule from now: booked transfers at the reference rate,
        best-effort ones at their rate, tasks at their runtime, nothing earlier than now."""
        wf, settings = run.workflow_id, self.settings
        site_of = run.placement.task_site
        arrival: dict[tuple[str, str], datetime] = {}  # (file, site) → when it is (expected) there
        finish: dict[str, datetime] = {}

        def at(file: str, site: str) -> datetime:
            if (file, site) in arrival:
                return arrival[(file, site)]
            if file in self.present.get((wf, site), {}):
                arrival[(file, site)] = self.present[(wf, site)][file]
                return arrival[(file, site)]
            producer = run.workflow.producer.get(file)
            origin = site_of[producer] if producer else run.placement.data_site
            ready = task_finish(producer) if producer else run.start
            if origin == site:
                arrival[(file, site)] = ready
            else:
                record = self.scheduler.records.get(f"{wf}:{file}>{site}")
                if record and record.finished_at:
                    arrival[(file, site)] = record.finished_at
                elif record:
                    arrival[(file, site)] = max(record.offer_end, now)
                else:
                    nbytes = run.nbytes(file)
                    gbps = settings.reference_gbps if nbytes >= settings.reserve_threshold_bytes else settings.best_effort_gbps
                    arrival[(file, site)] = max(ready, now) + timedelta(seconds=nbytes * 8 / (gbps * 1e9))
            return arrival[(file, site)]

        def task_finish(task_id: str) -> datetime:
            if task_id in finish:
                return finish[task_id]
            record = self.tasks[(wf, task_id)]
            if record.finished_at:
                finish[task_id] = record.finished_at
            elif record.started_at:
                finish[task_id] = record.started_at + run.runtime(task_id)
            else:
                task = run.workflow.tasks[task_id]
                start = max([at(file, site_of[task_id]) for file in task.inputs] + [run.start, now])
                finish[task_id] = start + run.runtime(task_id)
            return finish[task_id]

        out = {}
        for transfer in run.placement.transfers:
            ready = task_finish(transfer.producer) if transfer.producer else run.start
            out[transfer_key(wf, transfer)] = max(ready, now)
        return out

    # ── the loop ──────────────────────────────────────────────────────────

    def run(self) -> CosimResult:
        settings = self.settings
        runtime_graph = build_runtime_graph()
        now = min(run.start for run in self.runs)
        first_tick = now
        ticks = deviations = reports = 0
        would_not_fit: list[tuple[datetime, str]] = []
        findings: list[str] = []
        started: set[str] = set()
        while now <= settings.end and not self._all_done():
            to_send: list[tuple[WorkflowRun, FileTransfer]] = []
            for run in self.runs:
                if run.workflow_id not in started and run.start <= now:
                    started.add(run.workflow_id)
                    for file in run.workflow.external_inputs:
                        self.present.setdefault((run.workflow_id, run.placement.data_site), {})[file] = now
                    to_send += [(run, t) for t in run.placement.transfers if t.producer is None]
            self._deliver(now)
            to_send += self._finish_tasks(now)
            self._start_tasks(now)
            for run, transfer in to_send:
                self._send(run, transfer, now)
            self._start_tasks(now)                    # a best-effort transfer may already be done
            if (now - first_tick).total_seconds() % settings.tick_seconds == 0:
                ticks += 1
                out = runtime_graph.invoke({"event": Tick(), "now": now}, context=self.ctx)
                deviations += len(out.get("deviations", []))
                reports += sum(len(rs) for rs in out.get("reports", {}).values())
                for d in out.get("deviations", []):
                    branch = "slow" if d.slow else "overrun" if d.overrun else "link"
                    findings.append(f"{now:%H:%M:%S} deviation {d.committed.commitment.transfer_id} ({branch}, {d.cause}, "
                                    f"recent {d.recent_gbps} Gbps)")
                for rs in out.get("reports", {}).values():
                    findings += [f"{now:%H:%M:%S} report {r.transfer_id} {r.outcome} {r.action or ''}" for r in rs]
                self._forecast_demand(now, would_not_fit)
            now += timedelta(seconds=settings.step_seconds)
        return CosimResult(list(self.scheduler.records.values()) + self.best_effort, list(self.tasks.values()),
                           ticks, deviations, reports, would_not_fit, findings)

    def _forecast_demand(self, now: datetime, would_not_fit: list[tuple[datetime, str]]) -> None:
        forecast = forecast_scinet_demand(self.ctx, now)
        for expected in forecast.expected:
            self.predictions.setdefault(expected.request.id, []).append(expected.request.window.earliest_start)
        would_not_fit += [(now, transfer_id) for transfer_id in forecast.would_not_fit]

    def _send(self, run: WorkflowRun, transfer: FileTransfer, now: datetime) -> None:
        nbytes = run.nbytes(transfer.file)
        if nbytes >= self.settings.reserve_threshold_bytes:
            record = self.scheduler.book(run, transfer, now, self.net)
            predictions = self.predictions.get(record.transfer_id, [])
            if predictions:
                record.first_prediction, record.last_prediction = predictions[0], predictions[-1]
            return
        seconds = nbytes * 8 / (self.settings.best_effort_gbps * 1e9)
        key = transfer_key(run.workflow_id, transfer)
        self.best_effort.append(TransferRecord(run.workflow_id, transfer.file, transfer.src_site, transfer.dst_site,
                                               nbytes, False, now, now + timedelta(seconds=seconds), key,
                                               finished_at=now + timedelta(seconds=seconds)))

    def _deliver(self, now: datetime) -> None:
        for record in self.scheduler.records.values():
            if record.finished_at is None and record.offer_start <= now:
                done = self.net.flow_trace(record.instance_id, now).finished_at
                if done is not None and done <= now:
                    record.finished_at = done
        for record in list(self.scheduler.records.values()) + self.best_effort:
            if record.finished_at is not None and record.finished_at <= now:
                self.present.setdefault((record.workflow_id, record.dst), {}).setdefault(record.file, record.finished_at)

    def _finish_tasks(self, now: datetime) -> list[tuple[WorkflowRun, FileTransfer]]:
        out = []
        for run in self.runs:
            for task_id, task in run.workflow.tasks.items():
                record = self.tasks[(run.workflow_id, task_id)]
                if record.started_at and record.finished_at is None and record.started_at + run.runtime(task_id) <= now:
                    record.finished_at = record.started_at + run.runtime(task_id)
                    for file in task.outputs:
                        self.present.setdefault((run.workflow_id, record.site), {})[file] = record.finished_at
                    out += [(run, t) for t in run.placement.transfers if t.producer == task_id]
        return out

    def _start_tasks(self, now: datetime) -> None:
        for run in self.runs:
            if run.start > now:
                continue
            for task_id, task in run.workflow.tasks.items():
                record = self.tasks[(run.workflow_id, task_id)]
                if record.started_at is None and all(file in self.present.get((run.workflow_id, record.site), {})
                                                     for file in task.inputs):
                    record.started_at = now

    def _all_done(self) -> bool:
        return all(record.finished_at is not None for record in self.tasks.values())


def reference_makespan(run: WorkflowRun) -> timedelta:
    """The run's makespan if every transfer were instant (compute only)."""
    finish: dict[str, timedelta] = {}

    def done(task_id: str) -> timedelta:
        if task_id not in finish:
            task = run.workflow.tasks[task_id]
            start = max([done(run.workflow.producer[f]) for f in task.inputs if f in run.workflow.producer] + [timedelta(0)])
            finish[task_id] = start + run.runtime(task_id)
        return finish[task_id]

    return max(done(task_id) for task_id in run.workflow.tasks)


def records_of(records: Iterable[TransferRecord], workflow_id: str, booked: bool) -> list[TransferRecord]:
    return [r for r in records if r.workflow_id == workflow_id and r.booked == booked]
