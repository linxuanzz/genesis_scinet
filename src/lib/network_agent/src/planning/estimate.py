"""Finish-time estimation: given a reserved rate, roughly how fast the transfer actually completes
(slide 19: predicted_finish p50 / p95 at achievable rate).

``RateModel`` is the hook for the step-9 Learning calibration. The first version only has
``IdealRateModel``: it assumes actual rate = reserved rate, so p50 = p95 = the placement's end time.
``finish_at_reserved_rate`` serves graph A's query: one placement, one rate. ``finish_at_expected_rates``
serves graph B (step 7): there the rate expected from now on varies over time (an outage, a congested
hop), so the input is a list of (start, end, gbps) spans rather than a placement.

Known limitation: once a calibrated model is used, an actual rate below the reserved rate makes p95
later than the end of the reserved window, so the transfer would overrun its reservation; placement
will then need to size reservations by the p95 rate.
"""

from datetime import datetime
from typing import Protocol

from .placement import Placement, bytes_at, duration

ExpectedRates = list[tuple[datetime, datetime, float]]   # (start, end, gbps) spans, in time order


class RateModel(Protocol):
    def finish_at_reserved_rate(self, placement: Placement, nbytes: int) -> tuple[datetime, datetime]:
        """The (p50, p95) times at which nbytes are through on a placement at its one reserved rate
        (graph A's query, before anything is booked)."""
        ...

    def finish_at_expected_rates(self, expected_rates: ExpectedRates,
                                 nbytes: float) -> tuple[datetime, datetime] | None:
        """The (p50, p95) times at which nbytes are through when the rate follows ``expected_rates``
        (graph B, from now on); None if they are not through by the end of the last span."""
        ...


class IdealRateModel:
    def finish_at_reserved_rate(self, placement: Placement, nbytes: int) -> tuple[datetime, datetime]:
        return placement.end, placement.end

    def finish_at_expected_rates(self, expected_rates: ExpectedRates,
                                 nbytes: float) -> tuple[datetime, datetime] | None:
        left = nbytes
        for span_start, span_end, gbps in expected_rates:
            if left <= 0:
                return span_start, span_start
            moved = bytes_at(gbps, (span_end - span_start).total_seconds())
            if gbps > 0 and moved >= left:
                done = span_start + duration(left, gbps)
                return done, done
            left -= moved
        if left <= 0 and expected_rates:
            return expected_rates[-1][1], expected_rates[-1][1]
        return None
