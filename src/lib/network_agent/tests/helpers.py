"""Parameters, time helper, demo topology and agent setup shared by the tests."""

from datetime import datetime, timezone

from ..config import load_config
from ..context import AgentContext
from ..estimate import IdealRateModel
from ..graphs.commit import build_commit_graph
from ..graphs.modify import build_modify_graph
from ..graphs.quote import build_quote_graph
from ..graphs.release import build_release_graph
from ..graphs.reserve import build_reserve_graph
from ..ledger import CapacityLedger
from ..schemas import (CommitRequest, ModifyRequest, QuoteRequest, RateSegment, ReleaseRequest, ReserveRequest,
                       TimeWindow, TransferRequest)
from ..sense import MockSense
from ..sim import MockNetwork
from ..telemetry import MockTelemetry
from ..topology import Topology

UTC = timezone.utc

CFG = {"slot_seconds": 900, "horizon_seconds": 86400, "reserve_ttl_seconds": 60, "quote_ttl_seconds": 900,
       "max_paths": 3, "rate_step_gbps": 10}


def t(hh, mm=0, day=20):
    return datetime(2026, 10, day, hh, mm, tzinfo=UTC)


# The physical network of slide 3: aps-beamline-8id ─APS-LCRC─ anl-n01 ─L0─ anl-n02 ─L1─ esnet-atl ─L2─ esnet-chi ─L3─ ornl-n01
# Link names are from slide 3; the slide gives no capacities, so all are assumed to be 100 Gbps.
# esnet-nash and L4 / L5 (40 Gbps each) are a made-up second transit path for multi-path tests; not in the slide.
TOPO = {
    "nodes": ["aps-beamline-8id", "anl-n01", "anl-n02", "esnet-atl", "esnet-chi", "esnet-nash", "ornl-n01"],
    "links": [
        {"id": "APS-LCRC", "a": "aps-beamline-8id", "b": "anl-n01", "capacity_gbps": 100},
        {"id": "L0", "a": "anl-n01", "b": "anl-n02", "capacity_gbps": 100},
        {"id": "L1", "a": "anl-n02", "b": "esnet-atl", "capacity_gbps": 100},
        {"id": "L2", "a": "esnet-atl", "b": "esnet-chi", "capacity_gbps": 100},
        {"id": "L3", "a": "esnet-chi", "b": "ornl-n01", "capacity_gbps": 100},
        {"id": "L4", "a": "esnet-atl", "b": "esnet-nash", "capacity_gbps": 40},
        {"id": "L5", "a": "esnet-nash", "b": "esnet-chi", "capacity_gbps": 40},
    ],
}

# Endpoints of the test transfers: anl-n02 (the ANL node next to ESnet) → ornl-n01 at ORNL
SRC, DST = "anl-n02", "ornl-n01"
L1 = "L1:anl-n02>esnet-atl"
L2 = "L2:esnet-atl>esnet-chi"                 # the hop used by background traffic in the slide-7 scenario
L2_BACK = "L2:esnet-chi>esnet-atl"
L3 = "L3:esnet-chi>ornl-n01"
L4 = "L4:esnet-atl>esnet-nash"
L5 = "L5:esnet-nash>esnet-chi"
MAIN = (L1, L2, L3)                           # main path, 3 hops
ALT = (L1, L4, L5, L3)                        # detour via esnet-nash, 4 hops; shares L1 and L3 with MAIN


# ── agent setup on the slide-7 network ─────────────────────────────────────

class CountingTelemetry(MockTelemetry):
    calls = 0

    def link_samples(self, *args, **kwargs):
        self.calls += 1
        return super().link_samples(*args, **kwargs)


def make_net(background_gbps=60):
    """The slide-7 network: before 12:00 others use background_gbps on L2 (default 60, leaving 40 Gbps)."""
    n = MockNetwork(Topology.from_dict(TOPO))
    n.add_background(L2, t(9), t(12), background_gbps)
    return n


def make_ctx(net):
    """Ledger, telemetry and SENSE all look at the same simulated network."""
    cfg = load_config(CFG)
    return AgentContext(cfg=cfg, topology=net.topology, ledger=CapacityLedger(net.topology, cfg, origin=t(9)),
                        telemetry=CountingTelemetry(net, validity_seconds=300),
                        sense=MockSense(net, vlan_range=(3001, 3010)), rate_model=IdealRateModel())


# ── requests ───────────────────────────────────────────────────────────────

def tr(id="T1", src=SRC, dst=DST, nbytes=50 * 10**12, window=(t(9), t(15)), **over):
    """A transfer request; the defaults are T1 of slide 7 (50 TB, 09:00–15:00)."""
    return TransferRequest(id=id, workflow_id="WF-1", priority=1, src=src, dst=dst, bytes=nbytes,
                           is_estimate=False, divisible=False,
                           window=TimeWindow(earliest_start=window[0], latest_finish=window[1]), **over)


def quote(graph, ctx, *transfers, mode="all_or_nothing", now=t(9)):
    """Run one quote with quote_id "q1"; returns the final graph state."""
    raw = QuoteRequest(quote_id="q1", bundle=list(transfers), mode=mode).model_dump()
    return graph.invoke({"raw": raw, "now": now}, context=ctx)


def quote_t1_t2(quote_id="q1"):
    """The demos' quote request: T1 of slide 7 (50 TB) and T2 (1 TB), all or nothing."""
    return QuoteRequest(quote_id=quote_id, bundle=[tr("T1"), tr("T2", nbytes=10**12)], mode="all_or_nothing")


# the demos' reserve and commit after quote_t1_t2: T1 at 12:00 @ 100 Gbps, T2 at 09:00 @ 40 Gbps
R1 = ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T1/2", "q1/T2/1"])
C1 = CommitRequest(request_id="c1", reserve_id="rsv-1")


def modify_t1(request_id, end, gbps):
    """A ModifyRequest giving R1's T1 offer (starts 12:00) the single segment [12:00, end) @ gbps."""
    return ModifyRequest(request_id=request_id, reserve_id="rsv-1", offer_id="q1/T1/2",
                         rate_profile=[RateSegment(start=t(12), end=end, gbps=gbps)])


def reserve(ctx, *offer_ids, quote_id="q1", now=t(9), **over):
    """Run the reserve branch for these offers, with request_id "r1"; returns the final graph state."""
    raw = ReserveRequest(request_id="r1", quote_id=quote_id, offer_ids=list(offer_ids), **over).model_dump()
    return build_reserve_graph().invoke({"raw": raw, "now": now}, context=ctx)


def commit(ctx, reserve_id="rsv-1", now=t(9), request_id="c1"):
    """Run the commit branch for this reservation; returns the final graph state."""
    raw = CommitRequest(request_id=request_id, reserve_id=reserve_id).model_dump()
    return build_commit_graph().invoke({"raw": raw, "now": now}, context=ctx)


def release(ctx, reserve_id="rsv-1", offer_ids=None, now=t(9), request_id="x1"):
    """Run the release branch (all offers still held unless offer_ids is given); returns the final graph state."""
    raw = ReleaseRequest(request_id=request_id, reserve_id=reserve_id, offer_ids=offer_ids).model_dump()
    return build_release_graph().invoke({"raw": raw, "now": now}, context=ctx)


def modify(ctx, offer_id, start, end, gbps, reserve_id="rsv-1", now=t(9), request_id="m1"):
    """Run the modify branch: give offer_id the single segment [start, end) @ gbps; returns the final graph state."""
    raw = ModifyRequest(request_id=request_id, reserve_id=reserve_id, offer_id=offer_id,
                        rate_profile=[RateSegment(start=start, end=end, gbps=gbps)]).model_dump()
    return build_modify_graph().invoke({"raw": raw, "now": now}, context=ctx)


def make_quoted_ctx(net):
    """An agent that has just quoted T1 (slide 7, 50 TB) and T2 (1 TB) together at 09:00:

        q1/T1/1  09:00 @  40 Gbps → 11:46:40      q1/T2/1  09:00 @  40 Gbps → 09:03:20
        q1/T1/2  12:00 @ 100 Gbps → 13:06:40      q1/T2/2  12:00 @ 100 Gbps → 12:01:20
        q1/T1/3  09:00 @  20 Gbps → 14:33:20      q1/T2/3  09:00 @  10 Gbps → 09:13:20
    """
    ctx = make_ctx(net)
    build_quote_graph().invoke({"raw": quote_t1_t2().model_dump(), "now": t(9)}, context=ctx)
    return ctx
