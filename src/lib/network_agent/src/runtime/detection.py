"""Detection (graph B): which of our commitments are not getting, or will not get, what we promised.

Two branches, per commitment:

    flow branch   transfers already running; looks at what they get now
      slow        (a) throughput below the reserved rate by more than progress_lag_tolerance of it.
                  Throughput is the rate a flow alert measured, else the rate since the previous reading;
                  a first reading has none (an average since the start would count bytes lost to damage
                  already over, which overrun covers). Located on the current slot of the path:
                      a hop down                       → link_down
                      a hop squeezed (observed < own)  → congestion
                      the path healthy                 → unlocated (an end host, a soft failure)
      overrun     (b) throughput fine, but the remaining bytes exceed what the reservation can still carry
                  from now on by more than the tolerance of them. Located on the booked slots since the
                  transfer started (a past slot explains bytes lost earlier) and ahead; with no damage,
                  late_start if it started after its reservation, else unlocated
    link branch   future slots, and transfers not started yet: a booked slot from now on where a hop is
                  down or squeezed → link_down / congestion

Detection only reads the ledger (measurement for now, forecast ahead); runtime/forecast.py fills it.
Whether a deviation actually makes the transfer late is decided afterwards, in triage (repair.py).

What runs depends on the event:

    tick         every commitment, both branches
    flow alert   the commitment of that flow, flow branch a only (telemetry can see a slow flow; it
                 cannot see b, which needs the reservation)
    link alert   the commitments booked in the slots that the forecast found newly short, link branch only

A commitment whose transfer has finished is not checked. ``find_deviations_on_damaged_hops`` (scan_path)
adds the commitments an event did not concern that cross a hop found damaged.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from ..context.context import AgentContext, Committed
from ..models.schemas import FLOW_ALERTS, Cause, FlowProgress, RateSegment, TelemetryAlert, Tick
from ..planning.placement import bytes_at, gbps_of
from ..state.ledger import EPS_GBPS, CapacityLedger
from .forecast import ShortSlots, refresh

Branch = Literal["slow", "overrun", "link"]
ALL_BRANCHES: frozenset[Branch] = frozenset({"slow", "overrun", "link"})


@dataclass(frozen=True)
class SlotDamage:
    """One booked slot on one hop where the hop gives less than we booked."""

    link_id: str
    start: datetime                                   # the slot
    end: datetime
    observed_gbps: float                              # capacity without us
    own_gbps: float                                   # all our bookings on the hop in the slot
    up: bool

    @property
    def cause(self) -> Cause:
        return "congestion" if self.up else "link_down"


@dataclass(frozen=True)
class Deviation:
    """One commitment that deviates, with what scan_path needs to judge it."""

    committed: Committed                              # commitment + its reserved offer (path, booking, request)
    cause: Cause
    links: tuple[str, ...]                            # the hops that locate the cause, in path order; empty if unlocated
    damage: tuple[SlotDamage, ...]                    # every damaged slot considered (also ahead), by time then path
    progress: FlowProgress                            # this reading
    slow: bool                                        # flow branch a fired
    overrun: bool                                     # flow branch b fired
    recent_gbps: float | None                         # rate since the previous reading; None without one

    @property
    def commitment_id(self) -> str:
        return self.committed.commitment.commitment_id

    @property
    def remaining_bytes(self) -> int:
        return self.committed.reserved_offer.request.bytes - self.progress.bytes_sent


@dataclass(frozen=True)
class Detection:
    deviations: list[Deviation]
    checked: list[str]                                # commitment ids looked at
    refreshed: list[str]                              # links re-measured or re-forecast


# ── entry points ──────────────────────────────────────────────────────────

def detect_deviations(ctx: AgentContext, event: Tick | TelemetryAlert, short: ShortSlots, now: datetime) -> Detection:
    """Graph B's detect_deviations: the commitments and branches the event concerns (module docstring)."""
    committed = ctx.committed()
    if isinstance(event, Tick):
        return find_deviations(ctx, committed, now, ALL_BRANCHES)
    if event.kind in FLOW_ALERTS:
        concerned = [c for c in committed if c.reserved_offer.instance_id == event.flow_id]
        measured = 0.0 if event.kind == "flow_stalled" else event.measured_gbps
        return find_deviations(ctx, concerned, now, frozenset({"slow"}), measured_gbps=measured)
    concerned = [c for c in committed if any((link, slot) in short for link in c.reserved_offer.placement.path
                                             for slot in ctx.ledger.booking(c.reserved_offer.booking_id).slot_gbps)]
    return find_deviations(ctx, concerned, now, frozenset({"link"}))


def find_deviations_on_damaged_hops(ctx: AgentContext, deviations: list[Deviation], checked: list[str],
                                    now: datetime) -> Detection:
    """Check the commitments not looked at yet (not in ``checked``) that cross a hop where one of these
    deviations was found damaged: an alert about one flow may reveal damage that hits others too."""
    damaged_links = {slot_damage.link_id for deviation in deviations for slot_damage in deviation.damage}
    checked_ids = set(checked)
    unchecked = [committed for committed in ctx.committed()
                 if committed.commitment.commitment_id not in checked_ids
                 and damaged_links & set(committed.reserved_offer.placement.path)]
    return find_deviations(ctx, unchecked, now, ALL_BRANCHES) if unchecked else Detection([], [], [])


def find_deviations(ctx: AgentContext, commitments: list[Committed], now: datetime,
                    branches: frozenset[Branch], measured_gbps: float | None = None) -> Detection:
    """Read the progress of these commitments, make the ledger valid over their bookings, and return
    those that deviate in the given branches. ``measured_gbps``: the throughput a flow alert measured."""
    unfinished: list[tuple[Committed, FlowProgress]] = []
    for committed in commitments:
        progress = ctx.flows.progress(committed.reserved_offer.instance_id, now)
        if progress.bytes_sent < committed.reserved_offer.request.bytes:
            unfinished.append((committed, progress))
        else:
            ctx.forget_repair(committed.commitment.commitment_id)
    spans = [(committed.reserved_offer.placement.path, progress.started_at or now, committed.reserved_offer.placement.end)
             for committed, progress in unfinished]
    refreshed = refresh(ctx, spans, now).refreshed
    deviations = []
    for committed, progress in unfinished:
        deviation = check_commitment(ctx, committed, progress, now, branches, measured_gbps)
        if deviation is not None:
            deviations.append(deviation)
        elif branches == ALL_BRANCHES:                # only a full check clears a past repair episode
            ctx.forget_repair(committed.commitment.commitment_id)
    return Detection(deviations, [committed.commitment.commitment_id for committed, _ in unfinished], refreshed)


# ── one commitment ────────────────────────────────────────────────────────

def check_commitment(ctx: AgentContext, committed: Committed, progress: FlowProgress, now: datetime,
                     branches: frozenset[Branch], measured_gbps: float | None = None) -> Deviation | None:
    """Run the given branches on one unfinished commitment; None if none fires."""
    ledger, tolerance = ctx.ledger, ctx.cfg.progress_lag_tolerance
    profile, nbytes = committed.commitment.rate_profile, committed.reserved_offer.request.bytes
    running = progress.started_at is not None
    recent_gbps = None
    slow = overrun = False
    if branches & {"slow", "overrun"}:
        instance_id = committed.reserved_offer.instance_id
        recent_gbps = recent_rate(ctx.progress_seen.get(instance_id), progress)
        ctx.progress_seen[instance_id] = progress
        if running:
            seen = measured_gbps if measured_gbps is not None else recent_gbps
            slow = "slow" in branches and seen is not None and is_short(reserved_rate(profile, now), seen, tolerance)
            remaining = nbytes - progress.bytes_sent
            carriable = bytes_carried(profile, now, profile[-1].end, remaining)
            overrun = "overrun" in branches and not slow and is_short(remaining, carriable, tolerance)

    ahead = damaged_slots(ledger, committed, now) if "link" in branches or slow else []
    past: list[SlotDamage] = []
    # 1. slow in flow branch: throughput is lower than the appointment
    if slow:                                          # located on the current slot
        current = ledger.current_slot(now)
        locating = [slot_damage for slot_damage in ahead if current is not None
                    and slot_damage.start == ledger.slot_start(current)]
        if "link" not in branches:
            ahead = locating                          # a flow alert looks at the current slot only
    # 2. overrun in flow branch: the remaining quantity exceeds the reserved quantity
    elif overrun:                                     # located since the start, past slots included
        past = damaged_slots(ledger, committed, progress.started_at, until=now)
        locating = past + ahead
    # 3. link branch: the booked time period from now on will be damaged?
    else:
        locating = ahead
    if not (slow or overrun or ahead):
        return None

    path = committed.reserved_offer.placement.path
    damage = sorted(set(past + ahead), key=lambda slot_damage: (slot_damage.start, path.index(slot_damage.link_id)))
    causes = {slot_damage.cause for slot_damage in locating}
    if "link_down" in causes:
        cause: Cause = "link_down"
    elif causes:
        cause = "congestion"
    elif overrun and progress.started_at > profile[0].start:
        cause = "late_start"
    else:
        cause = "unlocated"
    located = {slot_damage.link_id for slot_damage in locating}
    links = tuple(link for link in committed.reserved_offer.placement.path if link in located)
    return Deviation(committed=committed, cause=cause, links=links, damage=tuple(damage), progress=progress,
                     slow=slow, overrun=overrun, recent_gbps=recent_gbps)


# ── helpers ───────────────────────────────────────────────────────────────

def bytes_carried(profile: list[RateSegment], start: datetime | None, end: datetime, cap: float) -> int:
    """Bytes the reservation's rate profile carries over [start, end), at most cap."""
    if start is None or end <= start:
        return 0
    carried = sum(bytes_at(segment.gbps, (min(segment.end, end) - max(segment.start, start)).total_seconds())
                  for segment in profile if segment.start < end and start < segment.end)
    return min(cap, int(carried))


def is_short(expected: float, actual: float, tolerance: float) -> bool:
    """actual falls short of expected by more than ``tolerance`` of expected; exactly that much is not."""
    return expected - actual > tolerance * expected


def reserved_rate(profile: list[RateSegment], now: datetime) -> float:
    """The rate the reservation gives at now; 0 outside it."""
    return next((segment.gbps for segment in profile if segment.start <= now < segment.end), 0.0)


def recent_rate(previous: FlowProgress | None, current: FlowProgress) -> float | None:
    """The average rate between two readings of a flow."""
    if previous is None or previous.sampled_at >= current.sampled_at:
        return None
    seconds = (current.sampled_at - previous.sampled_at).total_seconds()
    return gbps_of(current.bytes_sent - previous.bytes_sent, seconds)


def average_rate(progress: FlowProgress, now: datetime) -> float | None:
    """The average rate since the transfer started; None before any time has passed."""
    if progress.started_at is None or now <= progress.started_at:
        return None
    return gbps_of(progress.bytes_sent, (now - progress.started_at).total_seconds())


def damaged_slots(ledger: CapacityLedger, committed: Committed, look_from: datetime,
                  until: datetime | None = None) -> list[SlotDamage]:
    """The commitment's booked slots that end after ``look_from`` (and start before ``until``) where some
    hop is down or gives less than all we book on it."""
    path, damage = committed.reserved_offer.placement.path, []
    for slot in sorted(ledger.booking(committed.reserved_offer.booking_id).slot_gbps):
        start, end = ledger.slot_start(slot), ledger.slot_start(slot + 1)
        if end <= look_from or (until is not None and start >= until):
            continue
        for link in path:
            observed, own = ledger.observed(link, slot), ledger.own(link, slot)
            if not observed.up or observed.gbps < own - EPS_GBPS:
                damage.append(SlotDamage(link, start, end, observed.gbps, own, observed.up))
    return damage

