"""Unit tests for the trace reader, the placement and the co-simulation (on a tiny hand-made workflow)."""

from datetime import timedelta
from pathlib import Path

from src.lib.network_agent.tests.helpers import make_ctx, make_net, t
from src.lib.wftrace.cosim import CosimSettings, Cosimulation, WorkflowRun, reference_makespan
from src.lib.wftrace.trace import Task, Workflow, load_workflow, place

ROOT = Path(__file__).resolve().parents[4]
TRACE = ROOT / "external/SciNetGenesis/workflows/example_workflows/1000genome-chameleon-2ch-100k-001.json"
SITES = {"individuals": "ornl-n01", "sifting": "ornl-n01", "individuals_merge": "anl-n02",
         "mutation_overlap": "anl-n02", "frequency": "anl-n02"}


def test_load_the_1000genome_trace():
    wf = load_workflow(TRACE)
    assert (len(wf.tasks), len(wf.file_bytes), len(wf.external_inputs)) == (52, 64, 12)
    assert wf.tasks["individuals_ID0000001"].program == "individuals"
    assert wf.producer["chr21n-1-1001.tar.gz"] == "individuals_ID0000001"


def test_place_lists_each_cross_site_file_once_per_destination():
    wf = load_workflow(TRACE)
    placement = place(wf, SITES, "aps-beamline-8id")
    vcf = [x for x in placement.transfers if x.file == "ALL.chr21.100000.vcf"]
    assert [(x.src_site, x.dst_site, len(x.consumers)) for x in vcf] == [("aps-beamline-8id", "ornl-n01", 10)]
    assert all(x.src_site != x.dst_site for x in placement.transfers)
    # individuals outputs go to the merge at ANL; the merge's output stays at ANL
    assert any(x.producer == "individuals_ID0000001" and x.dst_site == "anl-n02" for x in placement.transfers)
    assert not any(x.file == "chr21n.tar.gz" for x in placement.transfers)


def tiny():
    """produce (at ORNL, 10 min) writes 9 TB that consume (at ANL, 10 min) reads; a small file goes best effort."""
    tasks = {"produce": Task("produce", "produce", ("seed",), ("big", "small"), 60.0),
             "consume": Task("consume", "consume", ("big", "small"), ("out",), 60.0)}
    wf = Workflow("tiny", tasks, {"seed": 10**6, "big": 9 * 10**12, "small": 10**8, "out": 10**6},
                  {"big": "produce", "small": "produce", "out": "consume"})
    return wf, place(wf, {"produce": "ornl-n01", "consume": "anl-n02"}, "ornl-n01")


def test_cosim_books_large_transfers_and_runs_the_dag():
    net = make_net()
    ctx = make_ctx(net)
    wf, placement = tiny()
    runs = [WorkflowRun("WF-A", wf, placement, t(9), 1, 1.0, 10.0),
            WorkflowRun("WF-B", wf, placement, t(9, 30), 1, 1.0, 10.0)]
    settings = CosimSettings(step_seconds=10, tick_seconds=300, reserve_threshold_bytes=10**9, reference_gbps=20,
                             best_effort_gbps=10, end=t(15))
    result = Cosimulation(ctx, net, runs, settings).run()
    booked = sorted((r for r in result.transfers if r.booked), key=lambda r: r.workflow_id)
    assert [(r.workflow_id, r.file) for r in booked] == [("WF-A", "big"), ("WF-B", "big")]
    assert all(r.finished_at <= r.latest_finish for r in booked)
    assert sum(1 for r in result.transfers if not r.booked) == 2               # "small", once per workflow
    assert all(task.finished_at for task in result.tasks) and result.deviations == 0
    a = booked[0]
    assert a.ready_at == t(9, 10)                                               # after produce's 10 minutes
    assert a.first_prediction == t(9, 10)                                       # forecast at 09:00
    b = booked[1]
    assert b.first_prediction is not None and abs((b.first_prediction - b.ready_at).total_seconds()) < 60
    assert reference_makespan(runs[0]) == timedelta(minutes=20)
