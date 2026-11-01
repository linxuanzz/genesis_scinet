"""Simulated network: a stand-in for the digital twin, used to drive the agent without Mininet / VIT / SENSE.

It holds the "ground truth": the topology, capacity used by others (per time range), link outages
(per time range), and the capacity we have reserved through SENSE. The mock telemetry (step 3a)
reads from it and the mock SENSE (step 3b) reads and writes it, so both see the same network.
This is the layer that gets replaced when we move to Mininet.

"Background traffic" and "our reservations" are stored separately: SENSE admission control has to count
both, while telemetry reports only background traffic (see schemas.LinkSample for the semantics); our
own reservations are accounted for by the ledger's ``own``.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .topology import Path, Topology


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    gbps: float = 0.0


@dataclass
class MockNetwork:
    topology: Topology
    _background: dict[str, list[Interval]] = field(init=False)  # directed link → background usage
    _outages: dict[str, list[Interval]] = field(init=False)  # directed link → outage periods
    _ours: dict[str, tuple[Path, Interval]] = field(init=False, default_factory=dict)  # SENSE instance → (path, reservation)

    def __post_init__(self):
        self._background = {link: [] for link in self.topology.links}
        self._outages = {link: [] for link in self.topology.links}

    def add_background(self, link_id: str, start: datetime, end: datetime, gbps: float) -> None:
        """Others use gbps of capacity in one direction over [start, end)."""
        self._background[link_id].append(Interval(start, end, gbps))

    def add_outage(self, physical_link_id: str, start: datetime, end: datetime) -> None:
        """A physical link goes down (e.g. a fiber cut): both directions are unavailable at once."""
        directed = [d.id for d in self.topology.links.values() if d.link_id == physical_link_id]
        if not directed:
            raise KeyError(f"unknown link {physical_link_id!r}")
        for link in directed:
            self._outages[link].append(Interval(start, end))

    def add_ours(self, instance_id: str, path: Path, start: datetime, end: datetime, gbps: float) -> None:
        """Capacity we reserved through SENSE (called by the mock SENSE on propagate)."""
        self._ours[instance_id] = (path, Interval(start, end, gbps))

    def remove_ours(self, instance_id: str) -> None:
        del self._ours[instance_id]

    def segments(self, link_id: str, start: datetime, end: datetime,
                 include_ours: bool = False) -> list[tuple[datetime, datetime, bool, float]]:
        """Split [start, end) into segments with unchanged state, each as (start, end, is up, available capacity).

        include_ours=False (telemetry semantics): available = capacity − background usage.
        include_ours=True  (SENSE admission semantics): additionally subtract our SENSE reservations.
        """
        cap = self.topology.links[link_id].capacity_gbps
        used = list(self._background[link_id])
        if include_ours:
            used += [iv for path, iv in self._ours.values() if link_id in path]
        events = used + self._outages[link_id]
        cuts = sorted({start, end} | {t for iv in events for t in (iv.start, iv.end) if start < t < end})
        out = []
        for a, b in zip(cuts, cuts[1:]):
            up = not any(iv.start < b and a < iv.end for iv in self._outages[link_id])
            taken = sum(iv.gbps for iv in used if iv.start < b and a < iv.end)
            out.append((a, b, up, max(0.0, cap - taken) if up else 0.0))
        return out

    def headroom(self, path: Path, start: datetime, end: datetime) -> float:
        """For SENSE admission: the highest extra rate the whole path can still give at every instant of [start, end)."""
        return min(gbps for link in path for *_, gbps in self.segments(link, start, end, include_ours=True))
