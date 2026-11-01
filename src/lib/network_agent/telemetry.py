"""Telemetry interface: where the network agent pulls link capacity and state from (slide 10).

The network agent depends only on the ``TelemetrySource`` interface; whether a mock, the Telemetry
Agent or SENSE / Prometheus sits behind it is transparent to the agent.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from .ledger import CapacityLedger
from .schemas import LinkSample
from .sim import MockNetwork
from .topology import Path


class TelemetrySource(Protocol):
    def link_samples(self, link_ids: list[str], start: datetime, end: datetime,
                     now: datetime) -> list[LinkSample]:
        """Return samples for these directed links over [start, end); see ``schemas.LinkSample`` for the semantics."""
        ...


@dataclass
class MockTelemetry:
    """Read the "ground truth" from MockNetwork and return samples split at every state change."""

    network: MockNetwork
    validity_seconds: int   # sample lifetime, i.e. valid_until = now + validity_seconds

    def link_samples(self, link_ids: list[str], start: datetime, end: datetime,
                     now: datetime) -> list[LinkSample]:
        valid_until = now + timedelta(seconds=self.validity_seconds)
        return [
            LinkSample(link_id=link, start=a, end=b, up=up, available_gbps=gbps,
                       sampled_at=now, valid_until=valid_until, source="mock")
            for link in link_ids
            for a, b, up, gbps in self.network.segments(link, start, end)
        ]


def refresh_stale(ledger: CapacityLedger, source: TelemetrySource,
                  spans: Iterable[tuple[Path, datetime, datetime]], now: datetime) -> list[str]:
    """For each (path, start, end), find the ledger slots on the path whose observations are stale at now,
    pull fresh samples for all of them from the source in one call, and write them into the ledger.
    Returns the links that were refreshed."""
    stale: dict[str, set[int]] = {}               # directed link → stale slot indices
    for path, start, end in spans:
        start, end = max(start, ledger.origin), min(end, ledger.horizon_end)
        if start >= end:
            continue
        for link in path:
            for i in ledger.slots_covering(start, end):
                if ledger.is_stale(link, i, now):
                    stale.setdefault(link, set()).add(i)
    if stale:
        first = min(min(slots) for slots in stale.values())
        last = max(max(slots) for slots in stale.values())
        ledger.apply(source.link_samples(sorted(stale), ledger.slot_start(first), ledger.slot_start(last + 1), now))
    return sorted(stale)
