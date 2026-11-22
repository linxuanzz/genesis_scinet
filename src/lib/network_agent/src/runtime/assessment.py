"""Finish-time assessment of a deviating commitment: when its remaining bytes get through from now on
(graph B's scan_path, step 7). Not to be confused with the network forecast (future link capacity), which
fills the ledger this module reads.

The rate a circuit is expected to get is read off the ledger, slot by slot, from now on:

    a hop is down                  0
    a hop gives less than we book  the circuit's share of it, in proportion to its rate (as the network
                                   shares a congested hop among our circuits); our other bookings count
    otherwise                      the circuit's rate

So damage still ahead (a planned outage, congestion expected to last) lowers the expected rate, and
damage that is over does not. An off-path cause is not in the ledger: when the deviation is unlocated
and the transfer is still slow (its recent rate, or its average since it started if there is no earlier
reading, is below its reserved rate by more than the tolerance), that rate caps the expected rate. Slots
are read whole (the ledger keeps the lowest value in a slot), so the assessment errs on the slow side.

The ledger holds a typical (p50) and a pessimistic (p95) capacity per slot (runtime/forecast.py); the
expected rates are read under each, and ``RateModel.finish_at_expected_rates``, the calibration hook,
gives the p50 finish from the typical rates and the p95 finish from the pessimistic ones.
"""

from dataclasses import dataclass
from datetime import datetime

from ..context.context import AgentContext, Committed, ReservedOffer
from ..models.topology import Path
from ..planning.estimate import ExpectedRates
from ..state.ledger import EPS_GBPS, CapacityLedger, Quantile
from .detection import Deviation, average_rate
from .forecast import refresh


@dataclass(frozen=True)
class Assessment:
    """A deviation, judged: how many bytes are left, by when they must be through, and when they will be."""

    deviation: Deviation
    deadline: datetime                                # latest_finish, at most the ledger's horizon
    cap_gbps: float | None                            # an off-path limit on the rate from now on; None: links only
    finish: tuple[datetime, datetime] | None          # (p50, p95) under the reservation; None: not through by its end
    finish_if_kept: tuple[datetime, datetime] | None  # ... were the circuit kept at its rate past its end

    @property
    def committed(self) -> Committed:
        return self.deviation.committed

    @property
    def commitment_id(self) -> str:
        return self.deviation.commitment_id

    @property
    def remaining_bytes(self) -> int:
        return self.deviation.remaining_bytes

    @property
    def priority(self) -> int:
        return self.committed.reserved_offer.request.priority

    @property
    def finishes_in_reservation(self) -> bool:
        """The remaining bytes get through by the reservation's end (p95)."""
        return self.finish is not None and self.finish[1] <= self.committed.reserved_offer.placement.end


def expected_gbps(ledger: CapacityLedger, path: Path, slot: int, gbps: float, booking_id: str | None,
                  quantile: Quantile = "p95") -> float:
    """
    - The rate a circuit of gbps along path is expected to get in this slot. 
    - ``booking_id`` is the circuit's own booking: what it books in the slot now is replaced by gbps, so it is not counted twice. None for a
    circuit not booked yet.
    - Example: this flow wants 10 Gbps on path A→B→C.
        Link A-B: 40 Gbps available, 30 Gbps booked by us in total. Not oversubscribed, so the flow keeps 10 Gbps.
        Link B-C: 15 Gbps available, 20 Gbps booked by us in total. Oversubscribed, so the flow gets 15 × 10 / 20 = 7.5 Gbps.
        The result is the minimum over the links: 7.5 Gbps.
    """
    booked_now = ledger.booking(booking_id).slot_gbps.get(slot, 0.0) if booking_id else 0.0
    rate = gbps
    for link in path:
        capacity = ledger.observed(link, slot).capacity(quantile)
        if capacity <= EPS_GBPS:
            return 0.0
        ours = ledger.own(link, slot) - booked_now + gbps  # all we book on the hop, this circuit counted at gbps
        if ours > capacity + EPS_GBPS:
            rate = min(rate, capacity * gbps / ours)
    return rate


def expected_rates_on_circuit(ledger: CapacityLedger, path: Path, gbps: float, start: datetime, end: datetime,
                              booking_id: str | None, cap: float | None, quantile: Quantile = "p95") -> ExpectedRates:
    """The (start, end, gbps) spans a circuit is expected to get over [start, end), within the ledger's
    range."""
    start, end = max(start, ledger.origin), min(end, ledger.horizon_end)
    spans: ExpectedRates = []
    if start >= end:
        return spans
    for slot in ledger.slots_covering(start, end):
        span_start, span_end = max(start, ledger.slot_start(slot)), min(end, ledger.slot_start(slot + 1))
        rate = expected_gbps(ledger, path, slot, gbps, booking_id, quantile)
        if cap is not None:
            rate = min(rate, cap)
        
        # same rate as the slot before: merge
        if spans and spans[-1][1] == span_start and abs(spans[-1][2] - rate) <= EPS_GBPS:
            spans[-1] = (spans[-1][0], span_end, rate)                 
        else:
            spans.append((span_start, span_end, rate))
    return spans


def expected_rates_under_reservation(ledger: CapacityLedger, reserved_offer: ReservedOffer, now: datetime,
                                     cap: float | None, until: datetime | None = None,
                                     quantile: Quantile = "p95") -> ExpectedRates:
    """The spans expected from now under the reserved offer's booking; with ``until``, its last rate is
    also kept from its end to until (as if the circuit were extended)."""
    path, profile, booking_id = (reserved_offer.placement.path, reserved_offer.placement.rate_profile,
                                 reserved_offer.booking_id)
    spans: ExpectedRates = []
    for seg in profile:
        spans += expected_rates_on_circuit(ledger, path, seg.gbps, max(seg.start, now), seg.end, booking_id, cap, quantile)
    if until is not None:
        last = profile[-1]
        spans += expected_rates_on_circuit(ledger, path, last.gbps, max(last.end, now), until, booking_id, cap, quantile)
    return spans


def off_path_cap(deviation: Deviation, now: datetime, tolerance: float) -> float | None:
    """For an unlocated deviation, the rate the transfer still gets if that is below its reserved rate by
    more than the tolerance; None otherwise (located, recovered, or no rate to go by)."""
    if deviation.cause != "unlocated" or deviation.progress.started_at is None:
        return None
    seen_gbps = deviation.recent_gbps                  # since the previous reading
    if seen_gbps is None:                              # first reading: the average since the start
        seen_gbps = average_rate(deviation.progress, now)
    reserved_gbps = deviation.committed.reserved_offer.placement.gbps
    if seen_gbps is not None and seen_gbps < (1 - tolerance) * reserved_gbps:
        return seen_gbps
    return None


def finish_of(ctx: AgentContext, reserved_offer: ReservedOffer, nbytes: int, cap: float | None, now: datetime,
              until: datetime | None = None) -> tuple[datetime, datetime] | None:
    """(p50, p95) of nbytes under the reserved offer's booking (kept at its last rate until ``until``, if
    given): p50 from the typical capacities, p95 from the pessimistic ones; None if not through under p95."""
    p50_spans = expected_rates_under_reservation(ctx.ledger, reserved_offer, now, cap, until, "p50")
    p95_spans = expected_rates_under_reservation(ctx.ledger, reserved_offer, now, cap, until, "p95")
    pessimistic = ctx.rate_model.finish_at_expected_rates(p95_spans, nbytes)
    if pessimistic is None:
        return None
    typical = ctx.rate_model.finish_at_expected_rates(p50_spans, nbytes) or pessimistic
    return min(typical[0], pessimistic[1]), pessimistic[1]


def assess(ctx: AgentContext, deviation: Deviation, now: datetime) -> Assessment:
    reserved_offer, remaining = deviation.committed.reserved_offer, deviation.remaining_bytes
    cap = off_path_cap(deviation, now, ctx.cfg.progress_lag_tolerance)
    finish = finish_of(ctx, reserved_offer, remaining, cap, now)
    kept = finish_of(ctx, reserved_offer, remaining, cap, now, until=ctx.ledger.horizon_end)
    deadline = min(reserved_offer.request.window.latest_finish, ctx.ledger.horizon_end)
    deadline = min(deadline, ctx.repair_deadlines.get(deviation.commitment_id, deadline))
    return Assessment(deviation, deadline, cap, finish, kept)


def finish_under(ctx: AgentContext, reserved_offer: ReservedOffer, nbytes: int, cap: float | None,
                 now: datetime) -> tuple[datetime, datetime] | None:
    """(p50, p95) of nbytes under the reserved offer's booking as it now stands."""
    return finish_of(ctx, reserved_offer, nbytes, cap, now)


def assess_all(ctx: AgentContext, deviations: list[Deviation], now: datetime) -> tuple[list[Assessment], list[str]]:
    """Make the ledger valid on each deviation's path up to its deadline (a repair may need the time past
    the reservation's end), then assess each. Returns the assessments and the links refreshed."""
    spans = [(deviation.committed.reserved_offer.placement.path, now,
              deviation.committed.reserved_offer.request.window.latest_finish) for deviation in deviations]
    refreshed = refresh(ctx, spans, now).refreshed
    return [assess(ctx, deviation, now) for deviation in deviations], refreshed
