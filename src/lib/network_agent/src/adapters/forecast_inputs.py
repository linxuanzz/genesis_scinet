"""What the network forecast knows about the future of a link, besides the current measurement.

The forecast (runtime/forecast.py) estimates, for every future slot, the capacity non-SciNet traffic
leaves us. It reads three inputs through ``ForecastInputs``:

    planned_outages           the maintenance calendar: when a link will be down
    registered_reservations   non-SciNet reservations others registered (e.g. in SENSE): known exactly.
                              Optional in practice; a source without them returns none
    baseline                  what unregistered non-SciNet traffic usually is on a link at a given time
                              (statistical baseline from link history with SciNet's own traffic removed),
                              as a typical (p50) and a high (p95) value

Our own bookings never appear here: they are the ledger's ``own``. ``MockForecastInputs`` reads the
calendar and the registered reservations from the simulated network and takes the baseline as given
(zero unless set), since there is no traffic history yet.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol

from ..sim.sim import MockNetwork

Window = tuple[datetime, datetime]
Usage = tuple[datetime, datetime, float]          # (start, end, gbps)


class ForecastInputs(Protocol):
    def planned_outages(self, link_id: str, start: datetime, end: datetime) -> list[Window]:
        """Planned outages of this directed link overlapping [start, end)."""
        ...

    def registered_reservations(self, link_id: str, start: datetime, end: datetime) -> list[Usage]:
        """Registered non-SciNet reservations on this directed link overlapping [start, end)."""
        ...

    def baseline(self, link_id: str, start: datetime, end: datetime) -> tuple[float, float]:
        """Unregistered non-SciNet traffic usually seen on this directed link over [start, end): (p50, p95)
        in Gbps, p50 <= p95."""
        ...


@dataclass
class MockForecastInputs:
    network: MockNetwork
    baseline_gbps: dict[str, tuple[float, float]] = field(default_factory=dict)   # directed link → (p50, p95)

    def planned_outages(self, link_id: str, start: datetime, end: datetime) -> list[Window]:
        return [(iv.start, iv.end) for iv in self.network.planned_outages(link_id) if iv.start < end and start < iv.end]

    def registered_reservations(self, link_id: str, start: datetime, end: datetime) -> list[Usage]:
        return [(iv.start, iv.end, iv.gbps) for iv in self.network.known_background(link_id)
                if iv.start < end and start < iv.end]

    def baseline(self, link_id: str, start: datetime, end: datetime) -> tuple[float, float]:
        return self.baseline_gbps.get(link_id, (0.0, 0.0))
