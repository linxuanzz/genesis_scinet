"""Step 3b: SENSE interface and mock. Two-phase lifecycle, admission against the simulated network, VLAN allocation, injected failures."""

import pytest
from pydantic import ValidationError

from ..schemas import ServiceIntent, Terminal
from ..sense import MockSense, SenseError
from ..sim import MockNetwork
from ..telemetry import MockTelemetry
from ..topology import Topology
from .helpers import L2, TOPO, t
from .helpers import MAIN as MAIN_PATH

MAIN = list(MAIN_PATH)                        # ServiceIntent.path_inclusion is a list


@pytest.fixture
def net():
    return MockNetwork(Topology.from_dict(TOPO))


@pytest.fixture
def sense(net):
    return MockSense(net, vlan_range=(3001, 3002))


def intent(mbps=40_000, **over):
    base = dict(alias="scinet-c1", terminals=[Terminal(uri="urn:anl"), Terminal(uri="urn:ornl")],
                capacity_mbps=mbps, qos_class="guaranteedCapped", start=t(9), end=t(10), path_inclusion=MAIN)
    return ServiceIntent(**(base | over))


# ── ServiceIntent validation ──────────────────────────────────────────────

@pytest.mark.parametrize("over", [
    {"terminals": [Terminal(uri="urn:anl")]},                                  # only one endpoint
    {"terminals": [Terminal(uri="urn:anl"), Terminal(uri="urn:anl")]},         # both ends identical
    {"start": t(10), "end": t(9)},                                             # time range reversed
    {"qos_class": "premium"},                                                  # not one of SENSE's four QoS classes
    {"capacity_mbps": 0},
])
def test_bad_intent(over):
    with pytest.raises(ValidationError):
        intent(**over)


# ── two-phase lifecycle ───────────────────────────────────────────────────

def test_propagate_commit_cancel(sense):
    s = sense.propagate(intent(), now=t(8))
    assert (s.state, s.vlan, s.alias) == ("reserved", 3001, "scinet-c1")
    s = sense.commit(s.instance_id, now=t(8, 1))
    assert (s.state, s.changed_at) == ("committed", t(8, 1))
    s = sense.cancel(s.instance_id, now=t(8, 2))
    assert (s.state, s.vlan) == ("cancelled", None)
    assert sense.state(s.instance_id).state == "cancelled"


def test_cancel_a_reserved_instance(sense):
    s = sense.propagate(intent(), now=t(8))
    assert sense.cancel(s.instance_id, now=t(8, 1)).state == "cancelled"


@pytest.mark.parametrize("bad", ["commit_twice", "commit_unknown", "cancel_twice"])
def test_invalid_transitions(sense, bad):
    s = sense.propagate(intent(), now=t(8))
    if bad == "commit_twice":
        sense.commit(s.instance_id, now=t(8))
        with pytest.raises(SenseError) as e:
            sense.commit(s.instance_id, now=t(8))
        assert e.value.reason == "invalid_state"
    elif bad == "commit_unknown":
        with pytest.raises(SenseError) as e:
            sense.commit("si-999", now=t(8))
        assert e.value.reason == "not_found"
    else:
        sense.cancel(s.instance_id, now=t(8))
        with pytest.raises(SenseError) as e:
            sense.cancel(s.instance_id, now=t(8))
        assert e.value.reason == "invalid_state"


def test_vlan_pool_and_reuse(sense):
    a = sense.propagate(intent(10_000), now=t(8))
    b = sense.propagate(intent(10_000), now=t(8))
    assert (a.vlan, b.vlan) == (3001, 3002)
    with pytest.raises(SenseError) as e:
        sense.propagate(intent(10_000), now=t(8))                 # the pool has only two
    assert e.value.reason == "no_vlan"
    sense.cancel(a.instance_id, now=t(8))
    assert sense.propagate(intent(10_000), now=t(8)).vlan == 3001  # reusable after release


# ── admission against the simulated network ───────────────────────────────

def test_admission_sees_background_traffic(net, sense):
    net.add_background(L2, t(9, 30), t(10), 40)               # occupies only the second half, still counts
    with pytest.raises(SenseError) as e:
        sense.propagate(intent(70_000), now=t(8))
    assert e.value.reason == "insufficient_capacity"
    assert sense.propagate(intent(60_000), now=t(8)).state == "reserved"


def test_admission_sees_outage(net, sense):
    net.add_outage("L3", t(9, 50), t(10, 30))
    with pytest.raises(SenseError):
        sense.propagate(intent(1_000), now=t(8))


def test_ours_counts_for_sense_but_not_for_telemetry(net, sense):
    """After we reserve 60: SENSE has only 40 left to give; telemetry still reports 100 (semantics: excludes our own)."""
    s = sense.propagate(intent(60_000), now=t(8))
    with pytest.raises(SenseError):
        sense.propagate(intent(50_000), now=t(8))
    tele = MockTelemetry(net, validity_seconds=300)
    assert tele.link_samples([L2], t(9), t(10), now=t(8))[0].available_gbps == 100
    sense.cancel(s.instance_id, now=t(8))
    assert sense.propagate(intent(50_000), now=t(8)).state == "reserved"   # capacity comes back after release


# ── injected failures ─────────────────────────────────────────────────────

def test_injected_commit_failure_leaves_reserved(sense):
    s = sense.propagate(intent(), now=t(8))
    sense.fail_next("commit")
    with pytest.raises(SenseError) as e:
        sense.commit(s.instance_id, now=t(8))
    assert e.value.reason == "injected"
    assert sense.state(s.instance_id).state == "reserved"     # a failure does not change the state
    assert sense.commit(s.instance_id, now=t(8)).state == "committed"   # fails only once


def test_injected_propagate_failure_takes_nothing(net, sense):
    sense.fail_next("propagate")
    with pytest.raises(SenseError):
        sense.propagate(intent(100_000), now=t(8))
    assert net.headroom(tuple(MAIN), t(9), t(10)) == 100
