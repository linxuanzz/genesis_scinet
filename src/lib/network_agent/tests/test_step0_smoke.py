"""Step 0: environment and skeleton self-check. Run: python -m pytest <path to network_agent>/tests"""

from typing import TypedDict

import pytest
import yaml
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from ..src.models.config import load_config
from .helpers import CFG


def test_config_from_dict_and_section():
    assert load_config(CFG).slot_seconds == 900
    assert load_config({"tag": "x", "network_agent": CFG}).reserve_ttl_seconds == 60


def test_config_from_yaml(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(yaml.safe_dump({"network_agent": CFG}))
    assert load_config(p).horizon_seconds == 86400


@pytest.mark.parametrize("bad", [
    {k: v for k, v in CFG.items() if k != "slot_seconds"},  # missing
    {**CFG, "slot_secs": 900},                               # misspelled
    {**CFG, "slot_seconds": 0},                              # not positive
    {k: v for k, v in CFG.items() if k != "repair_retry_seconds"},
    {**CFG, "repair_retry_seconds": 0},
    {**CFG, "repair_retry_seconds": -1},
    {k: v for k, v in CFG.items() if k != "event_dedup_seconds"},
    {**CFG, "event_dedup_seconds": 0},
    {k: v for k, v in CFG.items() if k != "reroute_cooldown_seconds"},
    {**CFG, "reroute_cooldown_seconds": 0},
    {**CFG, "horizon_seconds": 1000},                        # not a whole number of slots
])
def test_config_rejects_bad_input(bad):
    with pytest.raises(ValidationError):
        load_config(bad)


def test_langgraph_runs():
    class S(TypedDict):
        n: int

    g = StateGraph(S)
    g.add_node("inc", lambda s: {"n": s["n"] + 1})
    g.add_edge(START, "inc")
    g.add_edge("inc", END)
    assert g.compile().invoke({"n": 1}) == {"n": 2}
