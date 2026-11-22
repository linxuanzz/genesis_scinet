"""Simulated network: a stand-in for the digital twin, used to drive the agent without Mininet / VIT / SENSE.

It holds the "ground truth": the topology, capacity used by others (per time range), link outages
(per time range), and the capacity we have reserved through SENSE. The mock telemetry (step 3a)
reads from it and the mock SENSE (step 3b) reads and writes it, so both see the same network.
This is the layer that gets replaced when we move to Mininet.

Background (non-SciNet) traffic and outages are either known in advance (registered reservations,
planned outages: the forecast inputs read them) or not (unregistered traffic, unplanned outages: only
telemetry sees them, once they happen).

"Background traffic" and "our reservations" are stored separately: SENSE admission control has to count
both, while telemetry reports only background traffic (see schemas.LinkSample for the semantics); our
own reservations are accounted for by the ledger's ``own``.

Step 7 adds the transfers themselves, for the runtime graph: ``start_flow`` says the WMS started moving
bytes over one of our SENSE instances, and ``flow_trace`` integrates the rate each flow actually gets
(see ``_rates``). ``add_slowdown`` injects a cause outside the links (e.g. a slow disk at an end host);
``switch_flow`` moves the rest of a transfer to another instance (the WMS following a reroute).
Each change to one of our reservations is kept with the time it took effect, so that a modify or
cancel changes the flows from then on and leaves the simulated past as it was.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models.topology import Path, Topology
from ..planning.placement import bytes_at, duration
from ..state.ledger import EPS_GBPS


@dataclass(frozen=True)
class Interval:
    start: datetime
    end: datetime
    gbps: float = 0.0
    known_in_advance: bool = True                   # background: a registered reservation; outage: a planned one.
                                                    # Only these reach the forecast inputs; the rest shows up in
                                                    # telemetry only once it happens


@dataclass(frozen=True)
class Slowdown:
    start: datetime
    end: datetime
    factor: float                                   # 0..1, multiplies the flow's rate over [start, end)


@dataclass(frozen=True)
class Flow:
    """A transfer the WMS runs over one of our SENSE instances: it begins sending at ``start``, nbytes in all,
    unless it is moved to another instance at ``stop``."""

    start: datetime
    nbytes: int
    stop: datetime | None = None


@dataclass(frozen=True)
class FlowTrace:
    """What a flow actually did up to some time: (start, end, gbps) segments, bytes sent, and when it finished."""

    segments: list[tuple[datetime, datetime, float]]
    sent: float
    finished_at: datetime | None

    @property
    def first_byte(self) -> datetime | None:
        """When the flow first moved a byte; None if it has not yet."""
        return next((a for a, _, gbps in self.segments if gbps > EPS_GBPS), None)

    def sent_by(self, at: datetime) -> float:
        """Bytes sent before ``at`` (at most the trace's end)."""
        return sum(bytes_at(gbps, (min(b, at) - a).total_seconds()) for a, b, gbps in self.segments if a < at)


@dataclass
class MockNetwork:
    topology: Topology
    _background: dict[str, list[Interval]] = field(init=False)  # directed link → background usage
    _outages: dict[str, list[Interval]] = field(init=False)  # directed link → outage periods
    _ours: dict[str, tuple[Path, Interval]] = field(init=False, default_factory=dict)  # SENSE instance → (path, reservation)
    _history: dict[str, list[tuple[datetime | None, Interval | None]]] = field(init=False, default_factory=dict)
                                                    # SENSE instance → (from when, reservation; None once cancelled);
                                                    # from None: since the beginning
    _paths: dict[str, Path] = field(init=False, default_factory=dict)   # SENSE instance → path, kept after cancel
    _flows: dict[str, Flow] = field(init=False, default_factory=dict)  # SENSE instance → the transfer running over it
    _slowdowns: dict[str, list[Slowdown]] = field(init=False, default_factory=dict)  # SENSE instance → slowdowns

    def __post_init__(self):
        self._background = {link: [] for link in self.topology.links}
        self._outages = {link: [] for link in self.topology.links}

    def add_background(self, link_id: str, start: datetime, end: datetime, gbps: float,
                       registered: bool = True) -> None:
        """Non-SciNet traffic uses gbps of capacity in one direction over [start, end). ``registered``: it is a
        reservation others registered (e.g. in SENSE), so the forecast knows it in advance; otherwise it is
        unregistered traffic, seen only through telemetry once it happens."""
        self._background[link_id].append(Interval(start, end, gbps, known_in_advance=registered))

    def add_outage(self, physical_link_id: str, start: datetime, end: datetime, planned: bool = True) -> None:
        """A physical link goes down: both directions are unavailable at once. ``planned``: it is in the
        maintenance calendar, so the forecast knows it in advance; otherwise (e.g. a fiber cut) it is seen
        only through telemetry and alerts once it happens."""
        directed = [d.id for d in self.topology.links.values() if d.link_id == physical_link_id]
        if not directed:
            raise KeyError(f"unknown link {physical_link_id!r}")
        for link in directed:
            self._outages[link].append(Interval(start, end, known_in_advance=planned))

    def known_background(self, link_id: str) -> list[Interval]:
        """The registered non-SciNet reservations on this directed link."""
        return [iv for iv in self._background[link_id] if iv.known_in_advance]

    def planned_outages(self, link_id: str) -> list[Interval]:
        """The planned outages of this directed link."""
        return [iv for iv in self._outages[link_id] if iv.known_in_advance]

    def add_ours(self, instance_id: str, path: Path, start: datetime, end: datetime, gbps: float,
                 at: datetime | None = None) -> None:
        """Capacity we reserved through SENSE (called by the mock SENSE on propagate and modify), in effect
        for the flows from ``at`` on (None: as if it had always been so)."""
        iv = Interval(start, end, gbps)
        self._ours[instance_id] = (path, iv)
        self._paths[instance_id] = path
        self._history.setdefault(instance_id, []).append((at, iv))

    def remove_ours(self, instance_id: str, at: datetime | None = None) -> None:
        del self._ours[instance_id]
        self._history[instance_id].append((at, None))

    def start_flow(self, instance_id: str, at: datetime, nbytes: int) -> None:
        """The WMS starts sending nbytes over this instance at ``at`` (later than the reservation: a late start)."""
        if instance_id not in self._ours:
            raise KeyError(f"no reservation {instance_id!r}")
        self._flows[instance_id] = Flow(at, nbytes)

    def switch_flow(self, old_instance: str, new_instance: str, at: datetime) -> None:
        """The WMS moves the rest of the transfer on old_instance to new_instance at ``at`` (after a reroute)."""
        old = self._flows[old_instance]
        left = old.nbytes - int(self.flow_trace(old_instance, at).sent)
        self._flows[old_instance] = Flow(old.start, old.nbytes, stop=at)
        self.start_flow(new_instance, at, left)

    def add_slowdown(self, instance_id: str, start: datetime, end: datetime, factor: float) -> None:
        """Over [start, end) the flow on this instance runs at ``factor`` of what the links give it, for a
        reason outside the network (e.g. the source disk reads slowly). 0 stalls it."""
        if not 0 <= factor <= 1:
            raise ValueError("factor must be within [0, 1]")
        self._slowdowns.setdefault(instance_id, []).append(Slowdown(start, end, factor))

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

    def headroom(self, path: Path, start: datetime, end: datetime, exclude: str | None = None) -> float:
        """For SENSE admission: the highest extra rate the whole path can still give at every instant of
        [start, end), not counting the reservation of instance ``exclude``."""
        held = self._ours.pop(exclude) if exclude in self._ours else None
        try:
            return min(gbps for link in path for *_, gbps in self.segments(link, start, end, include_ours=True))
        finally:
            if held is not None:
                self._ours[exclude] = held

    def reservation_at(self, instance_id: str, at: datetime) -> Interval | None:
        """The reservation of this instance as it stood at ``at``; None if there was none (yet, or any more)."""
        current = None
        for since, iv in self._history.get(instance_id, []):
            if since is None or since <= at:
                current = iv
        return current

    # ── our transfers (step 7) ────────────────────────────────────────────

    def flow_trace(self, instance_id: str, until: datetime) -> FlowTrace:
        """What the flow on this instance did up to ``until``; an empty trace if it has not started."""
        if instance_id not in self._history:
            raise KeyError(f"no reservation {instance_id!r}")
        return self._simulate(until).get(instance_id, FlowTrace([], 0.0, None))

    def _simulate(self, until: datetime) -> dict[str, FlowTrace]:
        """Run every started flow together from the earliest start to ``until``. Rates are constant between
        state changes and recomputed whenever one flow finishes, since that frees capacity for the others."""
        flows = {i: f for i, f in self._flows.items() if f.start < until}
        if not flows:
            return {}
        sent = {i: 0.0 for i in flows}
        segs: dict[str, list[tuple[datetime, datetime, float]]] = {i: [] for i in flows}
        done: dict[str, datetime] = {}
        cuts = sorted({c for c in self._changes(flows) if c < until} | {until})
        now = min(f.start for f in flows.values())
        for cut in (c for c in cuts if c > now):
            while now < cut:
                active = [i for i, f in flows.items()
                          if f.start <= now and i not in done and (f.stop is None or now < f.stop)]
                rates = self._rates(active, now)
                finish = {i: max(now + duration(flows[i].nbytes - sent[i], g), now + timedelta(microseconds=1))
                          for i, g in rates.items() if g > EPS_GBPS}
                end = min([cut, *finish.values()])
                for i in active:
                    segs[i].append((now, end, rates[i]))
                    if i in finish and finish[i] <= end:
                        sent[i], done[i] = float(flows[i].nbytes), end
                    else:
                        sent[i] += bytes_at(rates[i], (end - now).total_seconds())
                now = end
        return {i: FlowTrace(segs[i], sent[i], done.get(i)) for i in flows}

    def _changes(self, flows: dict[str, Flow]) -> set[datetime]:
        """Every time at which some flow's rate may change, apart from other flows finishing."""
        links = {link for i in flows for link in self._paths[i]}
        ivs = [iv for link in links for iv in self._background[link] + self._outages[link]]
        ivs += [iv for versions in self._history.values() for _, iv in versions if iv is not None]
        ivs += [s for i in flows for s in self._slowdowns.get(i, [])]
        times = {f.start for f in flows.values()} | {f.stop for f in flows.values() if f.stop is not None}
        times |= {since for versions in self._history.values() for since, _ in versions if since is not None}
        return times | {t for iv in ivs for t in (iv.start, iv.end)}

    def _rates(self, active: list[str], at: datetime) -> dict[str, float]:
        """The rate each active flow gets at ``at``: min(its reserved rate, what each hop leaves it) × its
        slowdown factor. A hop leaves capacity − background; if that is less than the reserved rates of our
        flows on it, they share it in proportion to those rates. A down hop, or a time outside the
        reservation as it stood at ``at``, gives 0."""
        reserved = {}
        for i in active:
            iv = self.reservation_at(i, at)
            reserved[i] = iv.gbps if iv is not None and iv.start <= at < iv.end else 0.0
        rates = {}
        for i in active:
            path, r = self._paths[i], reserved[i]
            for link in path:
                if any(iv.start <= at < iv.end for iv in self._outages[link]):
                    r = 0.0
                    break
                left = self.topology.links[link].capacity_gbps - sum(
                    iv.gbps for iv in self._background[link] if iv.start <= at < iv.end)
                demand = sum(reserved[j] for j in active if link in self._paths[j])
                if demand > left + EPS_GBPS:
                    r = min(r, max(0.0, left) * reserved[i] / demand)
            for s in self._slowdowns.get(i, []):
                if s.start <= at < s.end:
                    r *= s.factor
            rates[i] = r
        return rates
