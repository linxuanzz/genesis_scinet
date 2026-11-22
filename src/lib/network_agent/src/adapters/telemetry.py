"""Telemetry interface: where the network agent pulls link capacity and state from (slide 10).

The network agent depends only on the ``TelemetrySource`` interface; whether a mock, the Telemetry
Agent or SENSE / Prometheus sits behind it is transparent to the agent. Telemetry measures: it is
asked only about past and current slots. Future slots come from the network forecast
(runtime/forecast.py), which also decides when to pull (``forecast.refresh``).

Step 7 adds, for the runtime graph, two PROVISIONAL pieces not yet agreed with the Telemetry Agent:
``FlowSource.progress`` (how far one of our transfers has got) and the alerts of ``schemas.TelemetryAlert``.
``MockFlows`` and ``MockAlerts`` produce both from the simulated network.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from itertools import count
from typing import Protocol

from ..models.schemas import FlowProgress, LinkSample, Subscribe, TelemetryAlert
from ..planning.placement import gbps_of
from ..sim.sim import MockNetwork


class TelemetrySource(Protocol):
    def link_samples(self, link_ids: list[str], start: datetime, end: datetime,
                     now: datetime) -> list[LinkSample]:
        """Return measured samples for these directed links over [start, end), a range that ends at the latest
        with the current slot; see ``schemas.LinkSample`` for the semantics."""
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


# ── flows and alerts (step 7, PROVISIONAL) ────────────────────────────────

class FlowSource(Protocol):
    def progress(self, instance_id: str, now: datetime) -> FlowProgress:
        """PROVISIONAL. When the transfer over this SENSE instance started and how many bytes it has sent by now."""
        ...


@dataclass
class MockFlows:
    """Progress as the simulated network computes it (MockNetwork.flow_trace)."""

    network: MockNetwork

    def progress(self, instance_id: str, now: datetime) -> FlowProgress:
        trace = self.network.flow_trace(instance_id, now)
        return FlowProgress(flow_id=instance_id, started_at=trace.first_byte, bytes_sent=int(trace.sent),
                            sampled_at=now, source="mock")


@dataclass
class MockAlerts:
    """Telemetry's push side, from the simulated network. ``poll`` returns the alerts whose condition has
    come to hold since the previous poll; an alert is sent again only after its condition has cleared.
    Link targets are directed link ids (a physical id also works for link_down / link_up); flow targets are
    SENSE instance ids. Without a time range, link_capacity_below watches the present instant."""

    network: MockNetwork
    _active: set[tuple] = field(init=False, default_factory=set)
    _ids: count = field(init=False, default_factory=lambda: count(1))

    def poll(self, subscriptions: list[Subscribe], now: datetime) -> list[TelemetryAlert]:
        current: dict[tuple, dict] = {}
        for sub in subscriptions:
            for target in sub.targets:
                for key, fields in self._conditions(sub, target, now):
                    current.setdefault((sub.kind, target, *key), fields | {"kind": sub.kind})
        fresh = [TelemetryAlert(alert_id=f"alert-{next(self._ids)}", observed_at=now, source="mock", **fields)
                 for key, fields in current.items() if key not in self._active]
        self._active = set(current)
        return fresh

    def _conditions(self, sub: Subscribe, target: str, now: datetime) -> Iterable[tuple[tuple, dict]]:
        """(key, alert fields) for each instance of the subscribed condition that holds at now."""
        net, kind = self.network, sub.kind
        if kind in ("link_down", "link_up"):
            directed = [d for d, link in net.topology.links.items() if target in (d, link.link_id)]
            outages = {iv for d in directed for iv in net._outages[d]}
            for iv in sorted(outages, key=lambda iv: iv.start):
                if kind == "link_down" and iv.start <= now < iv.end:
                    yield (iv.start,), {"link_id": target, "start": iv.start}
                if kind == "link_up" and iv.end <= now:
                    yield (iv.end,), {"link_id": target, "start": iv.end}
        elif kind == "link_capacity_below":
            start, end = (sub.start, sub.end) if sub.start is not None else (now, now + timedelta(microseconds=1))
            for a, b, _, gbps in net.segments(target, start, end):
                if gbps < sub.threshold_gbps and (b - a).total_seconds() >= sub.min_duration_seconds:
                    span = {"start": a, "end": b} if sub.start is not None else {"start": now}
                    yield (a, b, gbps), {"link_id": target, **span, "measured_gbps": gbps}
        else:
            trace = net.flow_trace(target, now)
            if kind == "flow_finished":
                if trace.finished_at is not None:
                    yield (), {"flow_id": target, "start": trace.finished_at}
                return
            since = now - timedelta(seconds=sub.min_duration_seconds)
            if trace.finished_at is not None or trace.first_byte is None or trace.first_byte > since:
                return                                # a whole window of the flow running is needed
            gbps = gbps_of(trace.sent - trace.sent_by(since), sub.min_duration_seconds)
            if (kind == "flow_stalled" and gbps == 0) or (kind == "flow_below_rate" and gbps < sub.threshold_gbps):
                extra = {"measured_gbps": gbps} if kind == "flow_below_rate" else {}
                yield (), {"flow_id": target, "start": since, "end": now, **extra}
