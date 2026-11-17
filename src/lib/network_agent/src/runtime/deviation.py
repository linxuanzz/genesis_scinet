"""Deviation detection for graph B (step 7): which of our commitments are not getting what we promised.

Three signals, per commitment:

    behind       bytes sent vs bytes due, i.e. the reservation's rate profile integrated from the
                 transfer's actual start (so a late start is not "behind") to now. The transfer is
                 behind once it lags by more than progress_lag_tolerance of what is due. This is the
                 main signal for a running transfer.
    overrun      a running transfer whose remaining bytes exceed what its reservation can still carry
                 from now on, by more than the same tolerance of them: it cannot finish inside the
                 reservation even at the full reserved rate. This catches a late start, and a lag too
                 small to be "behind" that would still leave bytes after the circuit ends.
    link level   after refreshing the observations, a slot the commitment has booked where a hop has
                 observed < own (observed = capacity without us, see schemas.LinkSample): our bookings
                 there exceed what the hop gives. This locates the hop, and covers commitments that
                 have not started yet.

A commitment deviates if it is behind or overruns, or if a slot it has booked, now or later, is damaged.
Damage in slots already over (since the transfer started) only serves to locate a lag. The cause:

    link_down    a damaged slot on a hop that is down
    congestion   otherwise a damaged slot: the hop is up but leaves less than we booked
    late_start   no damage, and the transfer started after its reservation did: the overrun is ours to
                 report, not the network's fault
    unlocated    behind or overrunning, yet no hop shows damage: the reason is off the path (an end host,
                 say); left to the learning graph to attribute

What is checked depends on the event. A tick checks every commitment and refreshes stale observations
only. A link alert checks the commitments over that link, a flow alert the commitment of that flow, and
both pull the alerted links afresh even where their observations are still valid: the alert says they
changed. A commitment whose transfer has finished is not checked. ``find_deviations_on_damaged_hops``
adds the commitments an event did not concern that cross a hop found damaged (graph B's scan_path).
"""

from dataclasses import dataclass
from datetime import datetime
from ..adapters.telemetry import refresh_stale
from ..context.context import AgentContext, Committed
from ..models.schemas import FLOW_ALERTS, Cause, FlowProgress, RateSegment, TelemetryAlert, Tick
from ..planning.placement import bytes_at, gbps_of
from ..state.ledger import EPS_GBPS, CapacityLedger


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
    links: tuple[str, ...]                            # the damaged hops, in path order; empty when unlocated
    damage: tuple[SlotDamage, ...]                    # the damaged slots considered, by time then path order
    progress: FlowProgress                            # this reading
    due_bytes: int                                    # due by now under the reservation (0 if not started)
    behind: bool                                      # the flow-level signal fired
    overrun: bool                                     # it cannot finish inside its reservation from here
    recent_gbps: float | None                         # rate since the previous reading; None without one

    @property
    def commitment_id(self) -> str:
        return self.committed.commitment.commitment_id

    @property
    def lag_bytes(self) -> int:
        return self.due_bytes - self.progress.bytes_sent

    @property
    def remaining_bytes(self) -> int:
        return self.committed.reserved_offer.request.bytes - self.progress.bytes_sent


@dataclass(frozen=True)
class Detection:
    deviations: list[Deviation]
    checked: list[str]                                # commitment ids looked at
    refreshed: list[str]                              # links whose observations were pulled


def due_bytes(profile: list[RateSegment], started_at: datetime | None, now: datetime, nbytes: float) -> int:
    """Bytes the reservation lets the transfer send over [started_at, now), at most nbytes."""
    if started_at is None or now <= started_at:
        return 0
    due = sum(bytes_at(segment.gbps, (min(segment.end, now) - max(segment.start, started_at)).total_seconds())
              for segment in profile if segment.start < now and started_at < segment.end)
    return min(nbytes, int(due))


def is_behind(expected: int, actual: int, tolerance: float) -> bool:
    """actual falls short of expected by more than ``tolerance`` of expected; exactly that much is not."""
    return expected - actual > tolerance * expected


def recent_rate(previous: FlowProgress | None, current: FlowProgress) -> float | None:
    """The average rate between two readings of a flow."""
    if previous is None or previous.sampled_at >= current.sampled_at:
        return None
    seconds = (current.sampled_at - previous.sampled_at).total_seconds()
    return gbps_of(current.bytes_sent - previous.bytes_sent, seconds)


def damaged_slots(ledger: CapacityLedger, committed: Committed, look_from: datetime) -> list[SlotDamage]:
    """The slots of the commitment's booking ending after ``look_from`` where some hop has observed < own or is down."""
    path, damage = committed.reserved_offer.placement.path, []
    for slot in sorted(ledger.booking(committed.reserved_offer.booking_id).slot_gbps):
        start, end = ledger.slot_start(slot), ledger.slot_start(slot + 1)
        if end <= look_from:
            continue
        for link in path:
            observed, own = ledger.observed(link, slot), ledger.own(link, slot)
            if not observed.up or observed.gbps < own - EPS_GBPS:
                damage.append(SlotDamage(link, start, end, observed.gbps, own, observed.up))
    return damage


def commitments_for_event(ctx: AgentContext, event: Tick | TelemetryAlert) -> tuple[list[Committed], set[str]]:
    """The commitments an event concerns, and the links to pull afresh."""
    all_committed = ctx.committed()
    if isinstance(event, Tick):
        return all_committed, set()
    if event.kind in FLOW_ALERTS:
        concerned = [committed for committed in all_committed if committed.reserved_offer.instance_id == event.flow_id]
        return concerned, {link for committed in concerned for link in committed.reserved_offer.placement.path}
    # the alert may name a directed link or a physical one (then both directions)
    alerted_links = {directed_id for directed_id, link in ctx.topology.links.items()
                     if event.link_id in (directed_id, link.link_id)}
    concerned = [committed for committed in all_committed
                 if alerted_links & set(committed.reserved_offer.placement.path)]
    return concerned, alerted_links & {link for committed in concerned
                                       for link in committed.reserved_offer.placement.path}


def find_deviations_for_event(ctx: AgentContext, event: Tick | TelemetryAlert, now: datetime) -> Detection:
    """Refresh what the event concerns and return the commitments that deviate (see the module docstring)."""
    commitments, force_refresh = commitments_for_event(ctx, event)
    return find_deviations(ctx, commitments, now, force_refresh)


def find_deviations_on_damaged_hops(ctx: AgentContext, deviations: list[Deviation], checked: list[str],
                                    now: datetime) -> Detection:
    """Check the commitments not looked at yet (not in ``checked``) that cross a hop where one of these
    deviations was found damaged: an alert about one flow may reveal damage that hits others too."""
    damaged_links = {slot_damage.link_id for deviation in deviations for slot_damage in deviation.damage}
    checked_ids = set(checked)
    unchecked = [committed for committed in ctx.committed()
                 if committed.commitment.commitment_id not in checked_ids
                 and damaged_links & set(committed.reserved_offer.placement.path)]
    return find_deviations(ctx, unchecked, now) if unchecked else Detection([], [], [])


def find_deviations(ctx: AgentContext, commitments: list[Committed], now: datetime,
                    force_refresh: set[str] = frozenset()) -> Detection:
    """Read the progress of these commitments, refresh their observations and return those that deviate."""
    # (commitment, its progress, when to look from: the transfer's start, or now if it has not started)
    unfinished: list[tuple[Committed, FlowProgress, datetime]] = []
    for committed in commitments:
        progress = ctx.flows.progress(committed.reserved_offer.instance_id, now)
        if progress.bytes_sent < committed.reserved_offer.request.bytes:
            unfinished.append((committed, progress, progress.started_at or now))
        else:
            ctx.forget_repair(committed.commitment.commitment_id)
    spans = [(committed.reserved_offer.placement.path, look_from, committed.reserved_offer.placement.end)
             for committed, _, look_from in unfinished]
    refreshed = refresh_stale(ctx.ledger, ctx.telemetry, spans, now, force=force_refresh)

    deviations = []
    tolerance = ctx.cfg.progress_lag_tolerance
    for committed, progress, look_from in unfinished:
        profile, nbytes = committed.commitment.rate_profile, committed.reserved_offer.request.bytes
        bytes_due = due_bytes(profile, progress.started_at, now, nbytes)
        behind = is_behind(bytes_due, progress.bytes_sent, tolerance)
        remaining_bytes = nbytes - progress.bytes_sent
        carriable_bytes = due_bytes(profile, now, profile[-1].end, remaining_bytes)  # the reservation can still carry
        overrun = progress.started_at is not None and is_behind(remaining_bytes, carriable_bytes, tolerance)
        instance_id = committed.reserved_offer.instance_id
        recent_gbps = recent_rate(ctx.progress_seen.get(instance_id), progress)
        ctx.progress_seen[instance_id] = progress
        damage = damaged_slots(ctx.ledger, committed, look_from)
        if not (behind or overrun):
            damage = [slot_damage for slot_damage in damage if slot_damage.end > now]  # past damage explains a lag only
        if not (behind or overrun or damage):
            ctx.forget_repair(committed.commitment.commitment_id)
            continue
        damage_causes = {slot_damage.cause for slot_damage in damage}
        started_late = progress.started_at is not None and progress.started_at > profile[0].start
        cause: Cause = ("link_down" if "link_down" in damage_causes else "congestion" if damage_causes
                        else "late_start" if started_late else "unlocated")
        damaged_links = {slot_damage.link_id for slot_damage in damage}
        links = tuple(link for link in committed.reserved_offer.placement.path if link in damaged_links)
        deviations.append(Deviation(committed=committed, cause=cause, links=links, damage=tuple(damage),
                                    progress=progress, due_bytes=bytes_due, behind=behind, overrun=overrun,
                                    recent_gbps=recent_gbps))
    return Detection(deviations, [committed.commitment.commitment_id for committed, _, _ in unfinished], refreshed)
