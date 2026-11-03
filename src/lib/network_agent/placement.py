"""Placement search for queries: on the ledger, find (start time, constant rate) placements for one
transfer along one path (slide 7, slide 19 P1).

Reads the ledger, never writes it; never calls SENSE. The first version uses three rules, each
producing one placement (later replaceable by a pluggable policy):

    earliest_start  the earliest possible start, at the highest rate sustainable from then on  → a1 in slide 7
    max_rate        the highest rate reachable in the window, at the earliest time it is reached  → a2
    min_rate        from the earliest start, the lowest rate that still meets latest_finish     → a3

The three rules are the trade-offs slide 7 describes: start early, occupy briefly, use little
capacity. The network agent only lists them and does not choose for the scheduling agent. Rates are
rounded to rate_step_gbps. Capacity checks use the same slot arithmetic as ledger.pending, so any
placement we return can definitely be booked at reserve time (provided the ledger has not changed).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from .ledger import EPS_GBPS, CapacityLedger
from .schemas import RateSegment, RejectReason, TransferRequest
from .topology import Path

BITS_PER_BYTE = 8
BITS_PER_GBIT = 1e9

Strategy = Literal["earliest_start", "max_rate", "min_rate"]
BlockedBy = Literal["own_commitment", "background_traffic"]


@dataclass(frozen=True)
class Placement:
    transfer_id: str
    path: Path
    start: datetime
    end: datetime
    gbps: float
    strategy: Strategy
    blocked_by: BlockedBy | None    # why the rate could not be higher: our own bookings or background traffic

    @property
    def rate_profile(self) -> list[RateSegment]:
        return [RateSegment(start=self.start, end=self.end, gbps=self.gbps)]


def dedupe(placements: list[Placement]) -> list[Placement]:
    """Placements with the same start and rate are indistinguishable to the scheduling agent (it cannot see paths): keep the first one."""
    seen, out = set(), []
    for p in placements:
        if (p.start, p.gbps) not in seen:
            seen.add((p.start, p.gbps))
            out.append(p)
    return out


def duration(nbytes: int, gbps: float) -> timedelta:
    return timedelta(seconds=nbytes * BITS_PER_BYTE / (gbps * BITS_PER_GBIT))


def _fits(ledger: CapacityLedger, path: Path, start: datetime, end: datetime, gbps: float,
          ignore_own: bool = False) -> bool:
    """The path can give gbps in every slot that [start, end) touches. ignore_own=True pretends we have no bookings of our own."""
    for i in ledger.slots_covering(start, end):
        if ignore_own:
            room = min(ledger.observed(link, i).gbps for link in path)
        else:
            room, _ = ledger.path_available(path, i)
        if room + EPS_GBPS < gbps:
            return False
    return True


def _max_rate_at(ledger: CapacityLedger, path: Path, nbytes: int, start: datetime, deadline: datetime,
                 rates: list[float], ignore_own: bool = False) -> float | None:
    """The highest rate sustainable when starting at start and finishing by deadline; None if no rate step fits."""
    for r in reversed(rates):
        end = start + duration(nbytes, r)
        if end <= deadline and _fits(ledger, path, start, end, r, ignore_own):
            return r
    return None


def search(ledger: CapacityLedger, path: Path, req: TransferRequest, now: datetime,
           rate_step: float) -> list[Placement] | RejectReason:
    earliest = max(req.window.earliest_start, now, ledger.origin)
    deadline = min(req.window.latest_finish, ledger.horizon_end)
    if earliest >= ledger.horizon_end:
        return RejectReason(cause="beyond_horizon", detail=f"window starts after ledger horizon {ledger.horizon_end}")
    if earliest >= deadline:
        return RejectReason(cause="no_capacity", detail="window has already passed")

    cap = min(ledger.topology.links[link].capacity_gbps for link in path)
    rates = [k * rate_step for k in range(1, int(cap // rate_step) + 1)]
    starts = [earliest] + [ledger.slot_start(i) for i in ledger.slots_covering(earliest, deadline)
                           if ledger.slot_start(i) > earliest]
    best = {s: r for s in starts if (r := _max_rate_at(ledger, path, req.bytes, s, deadline, rates))}
    if not best:
        return RejectReason(cause="no_capacity", detail="no start time in the window has enough room")

    def blocked(start: datetime, gbps: float) -> BlockedBy | None:
        if gbps >= rates[-1]:
            return None                     # already the path's top rate step, so not blocked
        free = _max_rate_at(ledger, path, req.bytes, start, deadline, rates, ignore_own=True)
        return "own_commitment" if free and free > gbps else "background_traffic"

    def make(start: datetime, gbps: float, strategy: Strategy, b: BlockedBy | None) -> Placement:
        return Placement(req.id, path, start, start + duration(req.bytes, gbps), gbps, strategy, b)

    s1 = min(best)
    top = max(best.values())
    s2 = min(s for s, r in best.items() if r == top)
    r3 = next(r for r in rates if r <= best[s1] and s1 + duration(req.bytes, r) <= deadline
              and _fits(ledger, path, s1, s1 + duration(req.bytes, r), r))
    found = [make(s1, best[s1], "earliest_start", blocked(s1, best[s1])),
             make(s2, top, "max_rate", blocked(s2, top)),
             make(s1, r3, "min_rate", None)]          # the low rate is chosen on purpose, not blocked

    unique = dedupe(found)
    if req.min_useful_rate_gbps is not None:
        useful = [p for p in unique if p.gbps + EPS_GBPS >= req.min_useful_rate_gbps]
        if not useful:
            return RejectReason(cause="below_min_useful_rate",
                                detail=f"best rate {top} Gbps < min useful {req.min_useful_rate_gbps}")
        unique = useful
    return unique
