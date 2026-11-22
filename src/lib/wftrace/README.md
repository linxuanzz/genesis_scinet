# wftrace

Drive the network agent with a real workflow trace (WfCommons WfFormat), in simulation.

| File | Role |
|---|---|
| `trace.py` | read a trace; `place` puts each program at a site and lists the cross-site file transfers |
| `cosim.py` | co-simulation: mock scheduling agent (books large transfers through graph A, and is the network agent's `SciNetDemandSource`) + mock WMS (runs the DAG), graph B every tick |
| `experiment.py` | the experiment entry shared by Exp3's variants: build from config, run, write report.md / timeline.html / csv |
| `timeline.py` | `timeline.html`, the demo view of a run |

Run (writes `runs/{timestamp}_{tag}_{hash}/timeline.html`):

    python scripts/run_experiment.py configs/exp_wftrace_1000genome_x2.yaml        # requests in trace order
    python scripts/run_experiment.py configs/exp_wftrace_1000genome_x2_edf.yaml    # earliest deadline first

Tests: `python -m pytest src/lib/wftrace/tests` from the repository root.
