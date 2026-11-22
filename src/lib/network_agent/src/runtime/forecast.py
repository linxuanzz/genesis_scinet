"""Network forecast: what capacity non-SciNet traffic leaves us on each link, slot by slot, from now on.

It keeps the ledger's ``observed`` filled and up to date; detection only reads it. Graph A reads the same
ledger, so planning and runtime see one picture.

Who writes which slot:

    past and current slot   telemetry's measurement, pulled when needed: expired, or a slot that still
                            holds a forecast because time has moved on (the measurement replaces it)
    future slots            this module (part A below)

Part A, non-SciNet traffic → ``observed`` (p50 / p95), per directed link and future slot:

    observed = nominal capacity − registered non-SciNet reservations − predicted unregistered traffic
    predicted unregistered traffic = w × start + (1 − w) × baseline,  w = exp(−lead time / decay)
        start      what the current measurement implies: nominal − registered now − measured observed
        baseline   what is usual on this link at that time (p50 / p95, from ForecastInputs)
      so a slot soon after now looks like now and a slot far ahead looks like usual, and the p50–p95
      gap widens with lead time up to the baseline's own spread
    planned outage (calendar)   down in both cases
    unplanned outage (a link found down, or a link_down alert; ``ctx.unplanned_outages``)
                                down in both cases until outage_repair_p50 after it began, down in the
                                pessimistic case only until outage_repair_p95
    every value is clamped to [0, nominal]

Part B, SciNet traffic → a forecast of SciNet's own future demand for planning / admission, kept apart
from ``observed``. PLACEHOLDER: the scheduling agent's side (``SciNetDemandSource``) does not exist yet.

Entry points, both returning the slots holding our bookings that went from enough to not enough under
the pessimistic value (``ForecastUpdate.short``):

    refresh(ctx, spans, now)          before reading the ledger over some spans (graph A and graph B)
    update_forecast(ctx, event, now)  graph B's first step: a tick recomputes the expired forecast values;
                                      a link alert re-measures the link and recomputes its forecast right
                                      away, without waiting for the affected slots to arrive
"""

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..context.context import AgentContext
from ..models.schemas import FLOW_ALERTS, TelemetryAlert, Tick
from ..models.topology import Path, Topology
from ..state.ledger import EPS_GBPS, CapacityLedger, Observation

FORECAST = "forecast"                             # Observation.source of the values written here
ShortSlots = set[tuple[str, int]]                 # (directed link, slot)


@dataclass(frozen=True)
class ForecastUpdate:
    short: ShortSlots                             # booked slots that went from enough to not enough (p95)
    refreshed: list[str]                          # links re-measured or re-forecast


# ── entry points ──────────────────────────────────────────────────────────

def refresh(ctx: AgentContext, spans: Iterable[tuple[Path, datetime, datetime]], now: datetime,
            force: Iterable[str] = ()) -> ForecastUpdate:
    """Make the ledger valid over each (path, start, end) before it is read: measure the past and current
    slots that need it, recompute the forecast of links with an expired future slot. Links in ``force``
    are re-measured and re-forecast even where still valid (an alert said they changed)."""
    ledger, force = ctx.ledger, set(force)
    to_measure: dict[str, set[int]] = {}
    to_forecast: set[str] = set()
    for path, start, end in spans:
        start, end = max(start, ledger.origin), min(end, ledger.horizon_end)
        if start >= end:
            continue
        for link in path:
            for slot in ledger.slots_covering(start, end):
                if ledger.slot_start(slot) > now:
                    if link in force or ledger.is_stale(link, slot, now):
                        to_forecast.add(link)
                elif link in force or needs_measurement(ledger, link, slot, now):
                    to_measure.setdefault(link, set()).add(slot)
    short = measure(ctx, to_measure, now)
    short |= forecast_links(ctx, to_forecast, now)
    return ForecastUpdate(short, sorted(set(to_measure) | to_forecast))


def update_forecast(ctx: AgentContext, event: Tick | TelemetryAlert, now: datetime) -> ForecastUpdate:
    """Graph B's update_forecast. A tick: recompute every link with an expired future slot. A link alert:
    note an outage starting or ending, re-measure the link now and recompute its forecast. A flow alert:
    nothing (it is about one transfer, not a link)."""
    ledger = ctx.ledger
    if isinstance(event, Tick):
        first = first_future_slot(ledger, now)
        expired = {link for link in ctx.topology.links
                   if any(ledger.is_stale(link, slot, now) for slot in range(first, ledger.n_slots))}
        return ForecastUpdate(forecast_links(ctx, expired, now), sorted(expired))
    if event.kind in FLOW_ALERTS:
        return ForecastUpdate(set(), [])
    links = alerted_links(ctx.topology, event.link_id)
    for link in links:
        if event.kind == "link_down" and not _planned_down(ctx, link, now):
            ctx.unplanned_outages.setdefault(link, event.start)
        elif event.kind == "link_up":
            ctx.unplanned_outages.pop(link, None)
    current = ledger.current_slot(now)
    short = measure(ctx, {link: {current} for link in links}, now) if current is not None else set()
    short |= forecast_links(ctx, links, now)
    return ForecastUpdate(short, sorted(links))


# ── measurement (past and current slots) ──────────────────────────────────

def needs_measurement(ledger: CapacityLedger, link: str, slot: int, now: datetime) -> bool:
    """A past or current slot needs a fresh measurement: expired, or still holding a forecast."""
    observation = ledger.observed(link, slot)
    return observation.valid_until <= now or observation.source == FORECAST


def measure(ctx: AgentContext, slots: dict[str, set[int]], now: datetime) -> ShortSlots:
    """Pull telemetry for these (link → past / current slots) and write it: the past slots in one call,
    the current slot in another, from now on only (what it was earlier in the slot is over). Note links
    found down outside the calendar, and links found up again."""
    slots = {link: wanted for link, wanted in slots.items() if wanted}
    if not slots:
        return set()
    ledger, current = ctx.ledger, ctx.ledger.current_slot(now)
    first = min(min(wanted) for wanted in slots.values())
    last = max(max(wanted) for wanted in slots.values())
    cells = [(link, slot) for link in slots for slot in range(first, last + 1)]
    before = {cell: enough(ledger, *cell) for cell in cells}
    past = sorted(link for link, wanted in slots.items() if any(slot != current for slot in wanted))
    if past:
        past_last = max(slot for link in past for slot in slots[link] if slot != current)
        ledger.apply(ctx.telemetry.link_samples(past, ledger.slot_start(first), ledger.slot_start(past_last + 1), now))
    now_measured = sorted(link for link, wanted in slots.items() if current in wanted)
    if now_measured:
        ledger.apply(ctx.telemetry.link_samples(now_measured, now, ledger.slot_start(current + 1), now))
    for link in now_measured:
        if not ledger.observed(link, current).up:
            if not _planned_down(ctx, link, now):
                ctx.unplanned_outages.setdefault(link, now)
        else:
            ctx.unplanned_outages.pop(link, None)
    return newly_short(ledger, cells, before)


# ── part A: forecast of non-SciNet traffic (future slots) ─────────────────

def forecast_links(ctx: AgentContext, links: Iterable[str], now: datetime) -> ShortSlots:
    """Recompute every future slot of these links (each starting from a fresh measurement now)."""
    links, ledger = sorted(set(links)), ctx.ledger
    first = first_future_slot(ledger, now)
    if not links or first >= ledger.n_slots:
        return set()
    current = ledger.current_slot(now)
    short: ShortSlots = set()
    if current is not None:
        short |= measure(ctx, {link: {current} for link in links if needs_measurement(ledger, link, current, now)}, now)
    observations: dict[tuple[str, int], Observation] = {}
    for link in links:
        observations |= forecast_link(ctx, link, first, now)
    before = {cell: enough(ledger, *cell) for cell in observations}
    ledger.put(observations)
    return short | newly_short(ledger, list(observations), before)


def forecast_link(ctx: AgentContext, link: str, first: int, now: datetime) -> dict[tuple[str, int], Observation]:
    """The forecast of one directed link for slots first … the horizon (see the module docstring)."""
    cfg, ledger, inputs = ctx.cfg, ctx.ledger, ctx.forecast_inputs
    nominal = ctx.topology.links[link].capacity_gbps
    registered = inputs.registered_reservations(link, min(now, ledger.slot_start(first)), ledger.horizon_end)
    planned = inputs.planned_outages(link, ledger.slot_start(first), ledger.horizon_end)

    # the starting point: unregistered traffic the current measurement implies (None: no usable measurement)
    start_load = None
    current = ledger.current_slot(now)
    if current is not None:
        measured = ledger.observed(link, current)
        if measured.up and measured.source != FORECAST:
            registered_now = peak_gbps(registered, now, now + timedelta(microseconds=1))
            start_load = _clamp(nominal - registered_now - measured.gbps, nominal)

    down_since = ctx.unplanned_outages.get(link)
    if down_since is not None:
        down_both_until = max(down_since + timedelta(seconds=cfg.outage_repair_p50_seconds), now)
        down_p95_until = max(down_since + timedelta(seconds=cfg.outage_repair_p95_seconds), now)
    valid_until = now + timedelta(seconds=cfg.forecast_validity_seconds)

    out = {}
    for slot in range(first, ledger.n_slots):
        start, end = ledger.slot_start(slot), ledger.slot_start(slot + 1)
        booked_by_others = peak_gbps(registered, start, end)
        usual_p50, usual_p95 = inputs.baseline(link, start, end)
        if start_load is None:
            load_p50, load_p95 = usual_p50, usual_p95
        else:
            weight = math.exp(-(start - now).total_seconds() / cfg.forecast_decay_seconds)
            load_p50 = weight * start_load + (1 - weight) * usual_p50
            load_p95 = weight * start_load + (1 - weight) * usual_p95
        p50 = _clamp(nominal - booked_by_others - load_p50, nominal)
        p95 = _clamp(nominal - booked_by_others - load_p95, nominal)
        up_p50 = up_p95 = True
        if any(a < end and start < b for a, b in planned):
            up_p50 = up_p95 = False
        elif down_since is not None:
            if start < down_both_until:
                up_p50 = up_p95 = False
            elif start < down_p95_until:
                up_p95 = False
        out[(link, slot)] = Observation(p95 if up_p95 else 0.0, FORECAST, now, valid_until, up_p95,
                                        p50_gbps=p50 if up_p50 else 0.0)
    return out


# ── helpers ───────────────────────────────────────────────────────────────

def first_future_slot(ledger: CapacityLedger, now: datetime) -> int:
    """The first slot that starts after now (the ledger's slot count if none does)."""
    current = ledger.current_slot(now)
    if current is not None:
        return current + 1
    return 0 if now < ledger.origin else ledger.n_slots


def alerted_links(topology: Topology, link_id: str) -> list[str]:
    """An alert may name a directed link or a physical one (then both directions)."""
    return sorted(directed for directed, link in topology.links.items() if link_id in (directed, link.link_id))


def enough(ledger: CapacityLedger, link: str, slot: int) -> bool | None:
    """Whether the slot gives what we booked on the hop (pessimistic value); None if we booked nothing."""
    own = ledger.own(link, slot)
    if own <= EPS_GBPS:
        return None
    observation = ledger.observed(link, slot)
    return observation.up and observation.gbps + EPS_GBPS >= own


def newly_short(ledger: CapacityLedger, cells: list[tuple[str, int]], before: dict) -> ShortSlots:
    return {cell for cell in cells if before[cell] is True and enough(ledger, *cell) is False}


def peak_gbps(usages: list[tuple[datetime, datetime, float]], start: datetime, end: datetime) -> float:
    """The highest total rate the usages reach at any instant of [start, end)."""
    instants = {start} | {a for a, _, _ in usages if start < a < end}
    return max((sum(g for a, b, g in usages if a <= at < b) for at in instants), default=0.0)


def _planned_down(ctx: AgentContext, link: str, now: datetime) -> bool:
    return bool(ctx.forecast_inputs.planned_outages(link, now, now + timedelta(microseconds=1)))


def _clamp(gbps: float, nominal: float) -> float:
    return min(max(gbps, 0.0), nominal)
