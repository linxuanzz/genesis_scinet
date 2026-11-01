"""Step 3a: simulated network → telemetry samples → ledger observed."""

import pytest
from pydantic import ValidationError

from ..config import load_config
from ..ledger import CapacityLedger
from ..schemas import LinkSample, RateSegment
from ..sim import MockNetwork
from ..telemetry import MockTelemetry
from ..topology import Topology
from .helpers import CFG, L2, L2_BACK, MAIN, TOPO, t


@pytest.fixture
def net():
    return MockNetwork(Topology.from_dict(TOPO))


@pytest.fixture
def tele(net):
    return MockTelemetry(net, validity_seconds=300)


@pytest.fixture
def ledger(net):
    return CapacityLedger(net.topology, load_config(CFG), origin=t(9))


def sample(**over):
    base = dict(link_id=L2, start=t(9), end=t(10), up=True, available_gbps=60,
                sampled_at=t(9), valid_until=t(9, 5), source="mock")
    return LinkSample(**(base | over))


# ── sample validation ─────────────────────────────────────────────────────

@pytest.mark.parametrize("over", [
    {"start": t(10), "end": t(9)},           # time range reversed
    {"valid_until": t(8)},                   # expires before it was sampled
    {"up": False, "available_gbps": 10},     # a down link cannot have available capacity
])
def test_bad_sample(over):
    with pytest.raises(ValidationError):
        sample(**over)


# ── simulated network → telemetry ─────────────────────────────────────────

def test_background_traffic_splits_segments(net, tele):
    net.add_background(L2, t(9, 45), t(10, 30), 40)
    got = [(s.start, s.end, s.available_gbps) for s in tele.link_samples([L2], t(9), t(11), now=t(9))]
    assert got == [(t(9), t(9, 45), 100), (t(9, 45), t(10, 30), 60), (t(10, 30), t(11), 100)]


def test_background_is_per_direction(net, tele):
    net.add_background(L2, t(9), t(10), 40)
    assert tele.link_samples([L2_BACK], t(9), t(10), now=t(9))[0].available_gbps == 100


def test_outage_hits_both_directions(net, tele):
    net.add_outage("L2", t(10), t(10, 15))
    for link in (L2, L2_BACK):
        mid = tele.link_samples([link], t(9), t(11), now=t(9))[1]
        assert (mid.start, mid.end, mid.up, mid.available_gbps) == (t(10), t(10, 15), False, 0)


def test_validity(tele):
    s = tele.link_samples([L2], t(9), t(10), now=t(9, 1))[0]
    assert (s.sampled_at, s.valid_until) == (t(9, 1), t(9, 6))


# ── telemetry → ledger ────────────────────────────────────────────────────

def test_topology_seed_is_stale_from_start(ledger):
    assert ledger.is_stale(L2, 0, now=t(9))


def test_apply_and_staleness(ledger):
    ledger.apply([sample()])
    o = ledger.observed(L2, 0)
    assert (o.gbps, o.source, o.valid_until) == (60, "mock", t(9, 5))
    assert not ledger.is_stale(L2, 0, now=t(9, 4))
    assert ledger.is_stale(L2, 0, now=t(9, 5))


def test_partial_slot_takes_min(ledger):
    """The sample boundary 09:20 falls inside the 09:15 slot: the slot takes the smaller of the two values, 30."""
    ledger.apply([sample(start=t(9), end=t(9, 20), available_gbps=80),
                  sample(start=t(9, 20), end=t(10), available_gbps=30)])
    assert [ledger.observed(L2, i).gbps for i in range(4)] == [80, 30, 30, 30]


def test_apply_clips_to_horizon(ledger):
    ledger.apply([sample(start=t(8), end=t(9, 15))])           # 08:00–09:00 is before the ledger, clipped
    assert ledger.observed(L2, 0).gbps == 60


def test_end_to_end_no_double_counting(net, tele, ledger):
    """Others use 40 (goes into observed), we book 30 (goes into own): available = 100 − 40 − 30 = 30, each counted once."""
    net.add_background(L2, t(9), t(10), 40)
    ledger.apply(tele.link_samples(list(MAIN), t(9), t(10), now=t(9)))
    ledger.pending("b1", MAIN, [RateSegment(start=t(9), end=t(9, 30), gbps=30)])
    assert (ledger.observed(L2, 0).gbps, ledger.own(L2, 0), ledger.available(L2, 0)) == (60, 30, 30)
    assert ledger.path_available(MAIN, 0) == (30, L2)
