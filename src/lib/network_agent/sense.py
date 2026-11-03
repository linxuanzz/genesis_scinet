"""SENSE interface: downward, the network agent configures the network only through ``SenseAdapter`` (slide 8).

Slide 8 calls this the swap point: whether real SENSE-O, NDT or Mininet sits behind it, the graphs
above do not change. We follow SENSE's two-phase flow (workflow_phased):

    propagate  reserve resources, no configuration pushed       ← reserve (``hold`` in the slides)
    commit     push configuration; SENSE rolls back on failure  ← commit
    cancel     return the resources                             ← release / reserve expiry
    modify     change bandwidth / time range in place            ← modify (step 5b)

Every failed call raises ``SenseError``; graph A's sense_call node uses it to take the rollback branch.
"""

from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from typing import Literal, Protocol

from .ledger import EPS_GBPS
from .schemas import ServiceIntent, ServiceState
from .sim import MockNetwork

Op = Literal["propagate", "commit", "cancel", "modify", "state"]


class SenseError(Exception):
    def __init__(self, op: Op, reason: Literal["insufficient_capacity", "invalid_state", "not_found",
                                                "no_vlan", "injected"], detail: str = ""):
        self.op, self.reason = op, reason
        super().__init__(f"{op} failed: {reason} {detail}".rstrip())


class SenseAdapter(Protocol):
    def propagate(self, intent: ServiceIntent, now: datetime) -> ServiceState: ...
    def commit(self, instance_id: str, now: datetime) -> ServiceState: ...
    def cancel(self, instance_id: str, now: datetime) -> ServiceState: ...
    def modify(self, instance_id: str, intent: ServiceIntent, now: datetime) -> ServiceState: ...
    def state(self, instance_id: str) -> ServiceState: ...


def cancel_instances(sense: SenseAdapter, instance_ids: list[str],
                     now: datetime) -> tuple[list[str], dict[str, SenseError]]:
    """Cancel each instance, going on past failures; one SENSE already reports as cancelled is skipped, so
    calling this again after a partial failure is safe. Returns (cancelled ids, {failed id: error})."""
    cancelled: list[str] = []
    failed: dict[str, SenseError] = {}
    for instance_id in instance_ids:
        try:
            if sense.state(instance_id).state != "cancelled":
                sense.cancel(instance_id, now)
            cancelled.append(instance_id)
        except SenseError as e:
            failed[instance_id] = e
    return cancelled, failed


@dataclass
class MockSense:
    """Admission control against MockNetwork's real capacity; failures can be injected to test rollback."""

    network: MockNetwork
    vlan_range: tuple[int, int]                       # VLAN pool [first, last]
    _states: dict[str, ServiceState] = field(init=False, default_factory=dict)
    _fail: dict[str, int] = field(init=False, default_factory=dict)
    _ids: count = field(init=False, default_factory=lambda: count(1))

    def fail_next(self, op: Op, times: int = 1) -> None:
        """Make the next ``times`` calls of op fail outright (simulates errors in SENSE or on the devices)."""
        self._fail[op] = self._fail.get(op, 0) + times

    def propagate(self, intent: ServiceIntent, now: datetime) -> ServiceState:
        self._maybe_fail("propagate")
        gbps = intent.capacity_mbps / 1000
        room = self.network.headroom(tuple(intent.path_inclusion), intent.start, intent.end)
        if gbps > room + EPS_GBPS:
            raise SenseError("propagate", "insufficient_capacity", f"need {gbps} Gbps, headroom {room}")
        vlan = self._free_vlan()
        instance_id = f"si-{next(self._ids)}"
        self.network.add_ours(instance_id, tuple(intent.path_inclusion), intent.start, intent.end, gbps)
        return self._set(ServiceState(instance_id=instance_id, alias=intent.alias, state="reserved",
                                      vlan=vlan, changed_at=now))

    def commit(self, instance_id: str, now: datetime) -> ServiceState:
        s = self._expect("commit", instance_id, "reserved")
        self._maybe_fail("commit")
        return self._set(s.model_copy(update={"state": "committed", "changed_at": now}))

    def cancel(self, instance_id: str, now: datetime) -> ServiceState:
        s = self._expect("cancel", instance_id, "reserved", "committed")
        self._maybe_fail("cancel")
        self.network.remove_ours(instance_id)
        return self._set(s.model_copy(update={"state": "cancelled", "vlan": None, "changed_at": now}))

    def modify(self, instance_id: str, intent: ServiceIntent, now: datetime) -> ServiceState:
        """Same instance, VLAN and state; the new bandwidth / time range is checked without the old one."""
        s = self._expect("modify", instance_id, "reserved", "committed")
        self._maybe_fail("modify")
        old = self.network._ours[instance_id]
        self.network.remove_ours(instance_id)
        gbps, path = intent.capacity_mbps / 1000, tuple(intent.path_inclusion)
        room = self.network.headroom(path, intent.start, intent.end)
        if gbps > room + EPS_GBPS:
            self.network._ours[instance_id] = old
            raise SenseError("modify", "insufficient_capacity", f"need {gbps} Gbps, headroom {room}")
        self.network.add_ours(instance_id, path, intent.start, intent.end, gbps)
        return self._set(s.model_copy(update={"changed_at": now}))

    def state(self, instance_id: str) -> ServiceState:
        s = self._states.get(instance_id)
        if s is None:
            raise SenseError("state", "not_found", instance_id)
        return s

    # ── internals ─────────────────────────────────────────────────────────

    def _maybe_fail(self, op: Op) -> None:
        if self._fail.get(op, 0) > 0:
            self._fail[op] -= 1
            raise SenseError(op, "injected")

    def _expect(self, op: Op, instance_id: str, *allowed: str) -> ServiceState:
        s = self._states.get(instance_id)
        if s is None:
            raise SenseError(op, "not_found", instance_id)
        if s.state not in allowed:
            raise SenseError(op, "invalid_state", f"{instance_id} is {s.state}")
        return s

    def _free_vlan(self) -> int:
        used = {s.vlan for s in self._states.values() if s.vlan is not None}
        first, last = self.vlan_range
        for v in range(first, last + 1):
            if v not in used:
                return v
        raise SenseError("propagate", "no_vlan", f"pool {first}-{last} exhausted")

    def _set(self, s: ServiceState) -> ServiceState:
        self._states[s.instance_id] = s
        return s
