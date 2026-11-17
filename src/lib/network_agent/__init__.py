"""SciNet Network Agent.

Design: the SciNet "Agent Orchestration" slides (slides 6–8, 12, 19–24) and the three-graph
design (protocol / runtime / learning).

The three execution graphs share one set of business modules. Graph nodes only orchestrate;
the logic lives in ordinary modules so that other graphs or other agents can reuse it.

Layout (src/, one folder per layer; a layer imports only from the layers listed before it):

    models/     config.py      parameters (all from config files; no magic numbers in code)
                schemas.py     inter-agent messages (TransferRequest, QueryRequest/Response, Offer …)
                topology.py    sites, links, paths
    state/      ledger.py      per-link, per-time-slot capacity ledger: available = observed − own
    planning/   placement.py   placement search for queries (the three offers of slide 7)
                estimate.py    RateModel: predicted finish p50 / p95 (hook for the step-9 calibration)
                circuit.py     placement → SENSE circuit and ServiceIntent (one new circuit per offer)
    sim/        sim.py         simulated network (stand-in for the digital twin: background traffic, link
                               outages, our transfers' actual progress)
    adapters/   telemetry.py   TelemetrySource interface + mock; provisional FlowSource and alert mocks
                sense.py       SenseAdapter interface + mock (SENSE-O / NDT / Mininet are interchangeable)
    context/    context.py     runtime context shared by the graphs (ledger, topology, external interfaces,
                               reservations and commitments)
    shared/     operations.py  state-changing steps on what we hold (modify in place, open a new circuit),
                               shared by graph A's branches and graph B's repairs
                reclaim.py     giving back what we hold: shared by release and the expiry sweep
    runtime/    deviation.py   graph B's detection: which commitments deviate, and why
                forecast.py    graph B's forecast: the rate a commitment can expect from now on, p50 / p95
                repair.py      graph B's triage, repair plan, repairs (extend / raise_rate / reroute / borrow)
                               and reports
    graphs/     protocol/      graph A: protocol.py (entry point: dedupe, sweep, route, remember) + query.py,
                               reserve.py, commit.py, release.py, modify.py, common.py
                runtime/       graph B: runtime.py
                (learning/     graph C, later)

Tests stay in tests/, outside src/, and import with package-relative paths (``from ..src.models.schemas``).

Conventions:
- ``reserve`` stands for the slides' ``hold``.
- Units: bandwidth in Gbps (float), data size in bytes (int), times are timezone-aware UTC datetimes.
- The ledger is kept per individual link rather than per (src, dst) pair as in slide 23: this is
  what lets us locate the congested hop and support multi-path capacity increases.
"""
