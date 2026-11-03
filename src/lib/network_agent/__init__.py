"""SciNet Network Agent.

Design: the SciNet "Agent Orchestration" slides (slides 6–8, 12, 19–24) and the three-graph
design (protocol / runtime / learning).

The three execution graphs share one set of business modules. Graph nodes only orchestrate;
the logic lives in ordinary modules so that other graphs or other agents can reuse it.
Planned modules:

    config.py      parameters (all from config files; no magic numbers in code)
    schemas.py     inter-agent messages (TransferRequest, QueryRequest/Response, Offer …)
    topology.py    sites, links, paths
    ledger.py      per-link, per-time-slot capacity ledger: available = observed − own
    sim.py         simulated network (stand-in for the digital twin: background traffic, link outages)
    telemetry.py   TelemetrySource interface + mock
    sense.py       SenseAdapter interface + mock (SENSE-O / NDT / Mininet are interchangeable)
    placement.py   placement search for queries (the three offers of slide 7)
    estimate.py    RateModel: predicted finish p50 / p95 (hook for the step-9 calibration)
    circuit.py     placement → SENSE circuit and ServiceIntent (step 5a: one new circuit per offer)
    context.py     runtime context shared by the three graphs (ledger, topology, external interfaces)
    reclaim.py     giving back what we hold: shared by release and the expiry sweep
    graphs/        graph A: protocol.py (the entry point: dedupe, sweep, route, remember) + query.py, reserve.py, commit.py,
                   release.py, modify.py;
                   runtime (graph B), learning (graph C)

Conventions:
- ``reserve`` stands for the slides' ``hold``.
- Units: bandwidth in Gbps (float), data size in bytes (int), times are timezone-aware UTC datetimes.
- The ledger is kept per individual link rather than per (src, dst) pair as in slide 23: this is
  what lets us locate the congested hop and support multi-path capacity increases.
"""
