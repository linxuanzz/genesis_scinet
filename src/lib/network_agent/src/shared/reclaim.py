"""Giving back what we hold: the pieces shared by graph A's release branch and the expiry sweep (step 5b).

``sweep_expired`` reclaims three kinds of leftovers:

    uncommitted reservations past expires_at   cancel in SENSE, give back the bookings, state → expired
    orphan instances                           a failed reserve could not cancel them; retry the cancel
    offers past the query's valid_until        dropped from offer_book; the query_id is remembered as expired

Graph A runs it lazily at the start of every message, before any branch reads the books, so a branch
never sees what should already be gone; ``now`` comes from the caller, which keeps it deterministic.
Hook: while no message arrives nothing is swept and SENSE keeps the expired instances, so a real
deployment should also call ``sweep_expired`` from a timer.

An instance SENSE fails to cancel keeps its booking (the network still carries it) and is retried by
the next sweep.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from ..adapters.sense import SenseAdapter, SenseError, cancel_instances
from ..context.context import AgentContext, Reservation, ReservedOffer


def cancel_reserved_offers(sense: SenseAdapter, reserved_offers: list[ReservedOffer],
                 now: datetime) -> tuple[list[str], dict[str, SenseError]]:
    """cancel_instances for reserved offers. Returns (cancelled offer_ids, {failed offer_id: error})."""
    offer_of = {o.instance_id: o.offer_id for o in reserved_offers}
    cancelled, failed = cancel_instances(sense, list(offer_of), now)
    return [offer_of[i] for i in cancelled], {offer_of[i]: e for i, e in failed.items()}


def give_back(ctx: AgentContext, r: Reservation, offer_ids: list[str],
              done: Literal["released", "expired"] = "released") -> None:
    """Give back the bookings of these reserved offers (their SENSE instances already cancelled), drop their
    commitments and mark them released; see Reservation.mark_released for ``done``."""
    by_offer_id = {o.offer_id: o for o in r.reserved_offers}
    for offer_id in offer_ids:
        ctx.ledger.free(by_offer_id[offer_id].booking_id)
        if offer_id in r.commitment_ids:
            del ctx.commitments[r.commitment_ids[offer_id]]
    r.mark_released(offer_ids, done)


@dataclass
class SweepReport:
    expired: list[str] = field(default_factory=list)              # reservations given back in full
    stuck: dict[str, list[str]] = field(default_factory=dict)     # reserve_id → offer_ids whose cancel failed
    orphans: list[str] = field(default_factory=list)              # orphan instances cancelled
    queries: list[str] = field(default_factory=list)               # queries whose offers were dropped


def sweep_expired(ctx: AgentContext, now: datetime) -> SweepReport:
    report = SweepReport()
    for r in ctx.reservations.values():
        if r.state != "reserved" or not r.is_expired(now):
            continue
        cancelled, failed = cancel_reserved_offers(ctx.sense, r.held, now)
        give_back(ctx, r, cancelled, done="expired")
        if failed:
            report.stuck[r.reserve_id] = list(failed)
        else:
            report.expired.append(r.reserve_id)

    cancelled, _ = cancel_instances(ctx.sense, list(ctx.orphans), now)
    for instance_id in cancelled:
        ctx.ledger.free(ctx.orphans.pop(instance_id))
    report.orphans = cancelled

    gone = [o for o, q in ctx.offer_book.items() if now >= q.expires_at]
    report.queries = sorted({ctx.offer_book[o].query_id for o in gone})
    for o in gone:
        del ctx.offer_book[o]
    ctx.expired_queries.update(report.queries)
    return report
