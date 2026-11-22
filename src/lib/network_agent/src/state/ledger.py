"""Capacity ledger: per directed link × per time slot, available = observed − own (slide 23).

- observed: capacity available when our own bookings are not counted (see schemas.LinkSample for the
  semantics). Initialized to the topology's configured capacity, then overwritten: past and current
  slots with telemetry samples by ``apply()``, future slots with the network forecast by ``put()``
  (runtime/forecast.py). Every number carries its source, sample time and expiry (slide 12: "every
  number carries its source"). A slot holds two values: ``gbps``, the pessimistic one (p95), which
  planning, detection and the capacity checks here use; and ``p50_gbps``, the typical one, which only
  the finish-time assessment reads to give a p50. A measurement has no spread: p50 = p95.
- own: the sum of our own bookings. A booking is in one of two states: pending (held at reserve time)
  or confirmed (after commit). A pending booking counts towards own as soon as it is written, so the
  very next query sees it (slide 19).

"Where is capacity deducted after accept": in ``pending()``. On failure ``rollback()`` returns it,
on success ``confirm()`` makes it permanent, and ``release()`` gives it back when no longer needed;
``replace()`` changes a booking's profile in place (modify, step 5b; graph B's repairs, step 7).

Time slots: slot i covers [origin + i·slot, origin + (i+1)·slot). A booking segment that touches a
slot occupies that whole slot at the segment's rate — this is the quantization error of slide 23:
the larger the slot, the more leftover capacity is wasted.
"""

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal

from ..models.config import NetAgentConfig
from ..models.schemas import LinkSample, RateSegment
from ..models.topology import Path, Topology

EPS_GBPS = 1e-9  # floating-point comparison tolerance, not a business parameter


class OutOfHorizon(ValueError):
    """A time falls outside the range the ledger covers (before origin or after the horizon)."""


class InsufficientCapacity(Exception):
    """A slot on some link lacks capacity. Carries which hop, how much is missing and what blocks it, for an
    offer's limited_by and for runtime congestion localization."""

    def __init__(self, link_id: str, slot_start: datetime, need: float, available: float,
                 limited_by: Literal["own_commitment", "background_traffic"]):
        self.link_id, self.slot_start, self.need, self.available, self.limited_by = (
            link_id, slot_start, need, available, limited_by)
        super().__init__(f"{link_id} @ {slot_start:%H:%M}: need {need} Gbps, available {available} ({limited_by})")


@dataclass(frozen=True)
class Observation:
    gbps: float            # capacity without us, pessimistic case (p95)
    source: str            # "topology" | "forecast" | "telemetry" | "mock" | ...
    at: datetime           # sample time
    valid_until: datetime  # expiry; the topology's initial values expire at origin, so they are refreshed before the first query
    up: bool = True        # link state in the pessimistic case; a down link has gbps 0 (tells an outage from congestion)
    p50_gbps: float | None = None   # capacity without us, typical case; None: same as the pessimistic case

    def capacity(self, quantile: "Quantile") -> float:
        """Capacity without us in this case; 0 while the link is down in it."""
        if quantile == "p50" and self.p50_gbps is not None:
            return self.p50_gbps
        return self.gbps if self.up else 0.0


Quantile = Literal["p50", "p95"]


@dataclass
class Booking:
    id: str
    path: Path
    slot_gbps: dict[int, float]                     # slot index → rate occupied in that slot
    state: Literal["pending", "confirmed"] = "pending"


@dataclass
class CapacityLedger:
    topology: Topology
    cfg: NetAgentConfig
    origin: datetime                                # start of slot 0; aligned to a slot boundary on construction
    _observed: dict[str, list[Observation]] = field(init=False)
    _bookings: dict[str, Booking] = field(init=False, default_factory=dict)
    _lock: threading.Lock = field(init=False, default_factory=threading.Lock)

    def __post_init__(self):
        slot = self.cfg.slot_seconds
        epoch = self.origin.timestamp()
        self.origin = self.origin - timedelta(seconds=epoch % slot)  # round down to a slot boundary
        self._observed = {d.id: [Observation(d.capacity_gbps, "topology", self.origin, self.origin)] * self.n_slots
                          for d in self.topology.links.values()}

    # ── time slots ────────────────────────────────────────────────────────

    @property
    def n_slots(self) -> int:
        return self.cfg.horizon_seconds // self.cfg.slot_seconds

    @property
    def horizon_end(self) -> datetime:
        return self.slot_start(self.n_slots)

    def slot_start(self, i: int) -> datetime:
        return self.origin + timedelta(seconds=i * self.cfg.slot_seconds)

    def slots_covering(self, start: datetime, end: datetime) -> range:
        """All slot indices that intersect [start, end)."""
        if start < self.origin or end > self.horizon_end:
            raise OutOfHorizon(f"[{start}, {end}) outside ledger [{self.origin}, {self.horizon_end})")
        slot = self.cfg.slot_seconds
        first = int((start - self.origin).total_seconds() // slot)
        last = int(-(-(end - self.origin).total_seconds() // slot))  # round up
        return range(first, last)

    # ── reads ─────────────────────────────────────────────────────────────

    def fork(self) -> "CapacityLedger":
        """Isolated allocation workspace for proposals; planning cannot change the live ledger."""
        trial = CapacityLedger(self.topology, self.cfg, self.origin)
        with self._lock:
            trial._observed = {link: list(slots) for link, slots in self._observed.items()}
            trial._bookings = {key: Booking(b.id, b.path, dict(b.slot_gbps), b.state)
                               for key, b in self._bookings.items()}
        return trial

    def observed(self, link_id: str, i: int) -> Observation:
        return self._observed[link_id][i]

    def own(self, link_id: str, i: int) -> float:
        return sum(b.slot_gbps.get(i, 0.0) for b in self._bookings.values() if link_id in b.path)

    def available(self, link_id: str, i: int) -> float:
        return max(0.0, self.observed(link_id, i).gbps - self.own(link_id, i))

    def path_available(self, path: Path, i: int) -> tuple[float, str]:
        """A path's available capacity in slot i = the minimum over its links; also returns which hop is the bottleneck."""
        return min((self.available(link, i), link) for link in path)

    def is_stale(self, link_id: str, i: int, now: datetime) -> bool:
        return self.observed(link_id, i).valid_until <= now

    def current_slot(self, now: datetime) -> int | None:
        """The slot now falls in; None outside the ledger's range."""
        if not self.origin <= now < self.horizon_end:
            return None
        return int((now - self.origin).total_seconds() // self.cfg.slot_seconds)

    def booking(self, booking_id: str) -> Booking:
        return self._bookings[booking_id]

    # ── writes ────────────────────────────────────────────────────────────

    def apply(self, samples: list[LinkSample]) -> None:
        """Write a batch of telemetry samples into observed. Parts of samples outside the ledger range are clipped.

        If a slot is covered by several samples in the same batch (a sample boundary falls inside the
        slot), take the minimum: available capacity must not be overestimated at any instant in the slot.
        A down sample wins a tie, so a slot with any outage in it reads as down.
        """
        per_slot: dict[tuple[str, int], Observation] = {}
        for s in samples:
            start, end = max(s.start, self.origin), min(s.end, self.horizon_end)
            if start >= end:
                continue
            obs = Observation(s.available_gbps, s.source, s.sampled_at, s.valid_until, s.up)
            for i in self.slots_covering(start, end):
                prev = per_slot.get((s.link_id, i))
                if prev is None or (obs.gbps, obs.up) < (prev.gbps, prev.up):
                    per_slot[(s.link_id, i)] = obs
        with self._lock:
            for (link_id, i), obs in per_slot.items():
                self._observed[link_id][i] = obs

    def put(self, observations: dict[tuple[str, int], Observation]) -> None:
        """Write observations slot by slot ((directed link, slot) → observation), as the forecast computes them."""
        with self._lock:
            for (link_id, i), obs in observations.items():
                self._observed[link_id][i] = obs

    def pending(self, booking_id: str, path: Path, profile: list[RateSegment]) -> None:
        """Hold capacity: first check that every slot on every link along the path suffices, and write only if
        all do; if any one falls short, nothing is written."""
        self.pending_group([(booking_id, path, profile)])

    def pending_group(self, bookings: list[tuple[str, Path, list[RateSegment]]]) -> None:
        """Hold capacity for several bookings, all or nothing (slide 19: one hold for the whole group).
        They are checked in order, each one seeing those before it, so two bookings that share a link
        cannot both take its last free capacity; if any one falls short, nothing is written."""
        plans = [(booking_id, path, self._slot_gbps(profile)) for booking_id, path, profile in bookings]
        with self._lock:
            written: list[str] = []
            try:
                for booking_id, path, slot_gbps in plans:
                    self._check_and_write(booking_id, path, slot_gbps)
                    written.append(booking_id)
            except Exception:
                for booking_id in written:
                    del self._bookings[booking_id]
                raise

    def confirm(self, booking_id: str) -> None:
        with self._lock:
            b = self._require(booking_id, "pending")
            b.state = "confirmed"

    def rollback(self, booking_id: str) -> None:
        """Undo a pending booking (e.g. when the SENSE call fails). Confirmed bookings use release instead."""
        with self._lock:
            self._require(booking_id, "pending")
            del self._bookings[booking_id]

    def release(self, booking_id: str) -> None:
        with self._lock:
            self._require(booking_id, "confirmed")
            del self._bookings[booking_id]

    def free(self, booking_id: str) -> None:
        """Give a booking back whatever its state: pending → rollback, confirmed → release."""
        if self.booking(booking_id).state == "pending":
            self.rollback(booking_id)
        else:
            self.release(booking_id)

    def replace(self, booking_id: str, profile: list[RateSegment], now: datetime | None = None) -> None:
        """Swap a booking's profile, same path and state, atomically; if the new one does not fit, the old
        one stays. Only what the new profile adds is checked (with the old one not counted): a slot where
        it asks for no more than the booking already holds is not checked again, since the capacity held
        there may have shrunk since (an outage, congestion) and keeping it takes nothing from anyone.
        Slots already over at ``now`` keep what they held: that is what was used."""
        slot_gbps = self._slot_gbps(profile)
        with self._lock:
            old = self._bookings.pop(booking_id)
            if now is not None:
                over = {i for i in slot_gbps.keys() | old.slot_gbps.keys() if self.slot_start(i + 1) <= now}
                slot_gbps = {i: g for i, g in slot_gbps.items() if i not in over}
                slot_gbps |= {i: old.slot_gbps[i] for i in over if i in old.slot_gbps}
            grows = {i for i, g in slot_gbps.items() if g > old.slot_gbps.get(i, 0.0) + EPS_GBPS}
            try:
                self._check_and_write(booking_id, old.path, slot_gbps, check=grows)
            except Exception:
                self._bookings[booking_id] = old
                raise
            self._bookings[booking_id].state = old.state

    def _slot_gbps(self, profile: list[RateSegment]) -> dict[int, float]:
        slot_gbps: dict[int, float] = {}
        for seg in profile:
            for i in self.slots_covering(seg.start, seg.end):
                slot_gbps[i] = max(slot_gbps.get(i, 0.0), seg.gbps)  # adjacent segments of one booking in the same slot: take the larger, don't double count
        return slot_gbps

    def _check_and_write(self, booking_id: str, path: Path, slot_gbps: dict[int, float],
                         check: set[int] | None = None) -> None:
        """Caller holds the lock. Checks the slots in ``check`` (all if None)."""
        if booking_id in self._bookings:
            raise ValueError(f"booking {booking_id!r} already exists")
        for link in path:
            for i, need in slot_gbps.items():
                if check is not None and i not in check:
                    continue
                avail = self.available(link, i)
                if need > avail + EPS_GBPS:
                    # enough without our own bookings → blocked by our own commitments; otherwise by background traffic
                    blocked = "own_commitment" if self.observed(link, i).gbps + EPS_GBPS >= need else "background_traffic"
                    raise InsufficientCapacity(link, self.slot_start(i), need, avail, blocked)
        self._bookings[booking_id] = Booking(booking_id, path, slot_gbps)

    def _require(self, booking_id: str, state: str) -> Booking:
        b = self._bookings.get(booking_id)
        if b is None:
            raise KeyError(f"no booking {booking_id!r}")
        if b.state != state:
            raise ValueError(f"booking {booking_id!r} is {b.state}, expected {state}")
        return b
