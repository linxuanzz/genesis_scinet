"""Runtime environment shared by the three graphs (the LangGraph runtime context).

A graph's state only records the work of "this one execution". Long-lived objects shared by all
requests — the ledger, the topology, external interfaces, and the books of query results,
reservations and commitments — live in the context instead: the caller builds it once and passes it on
every invoke (by design, the ledger stays out of state).

The three books form a chain, each entry pointing back to the previous one by id:

    offer_book     offer_id      → QueriedOffer  written by query's respond, dropped once the query expires (step 5b)
    reservations   reserve_id    → Reservation   written by reserve (step 5a)
    commitments    commitment_id → Commitment    written by commit (step 5a), dropped by release (step 5b)

Two smaller books serve the expiry sweep (reclaim.py): ``orphans``, SENSE instances that a failed reserve
could not cancel, and ``expired_queries``, so that a reserve against a dropped query is told it expired.
``answered`` caches successful replies so that graph A can answer a resent request (step 5b).
``progress_seen`` keeps the last progress reading of each flow, from which graph B derives its recent
rate (step 7); ``committed()`` lists what graph B watches. ``failed_repairs`` postpones identical repair
attempts until conditions change or a retry is due. ``reported_unresolved`` independently suppresses
duplicate reports to the scheduling agent.
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from typing import Literal

from ..adapters.sense import SenseAdapter
from ..adapters.telemetry import FlowSource, TelemetrySource
from ..models.config import NetAgentConfig
from ..models.schemas import Cause, Commitment, DeviationReport, FlowProgress, Msg, ServiceIntent, TransferRequest
from ..models.topology import Path, Topology
from ..planning.estimate import RateModel
from ..planning.placement import Placement
from ..state.ledger import CapacityLedger


@dataclass(frozen=True)
class QueriedOffer:
    """What we remember about an offer returned by a query. The scheduling agent only sees the Offer; the request it
    answers (needed later for the commitment's workflow_id) and the placement behind it (path, rule) stay here."""

    query_id: str
    request: TransferRequest
    placement: Placement
    expires_at: datetime                              # the query's valid_until; reserve refuses the offer after this


@dataclass(frozen=True)
class ReservedOffer:
    """One offer inside a reservation: the ledger booking and the SENSE instance that hold it."""

    offer_id: str
    request: TransferRequest                          # the transfer it serves (offer_book may drop the query before commit)
    placement: Placement                              # what was actually booked (may differ from the query once
                                                      # the alternate-path hook exists); gives the commitment's rate
    booking_id: str                                   # ledger booking; pending until commit
    intent: ServiceIntent                             # what was sent to SENSE; its terminals become the EndpointBinding
    instance_id: str                                  # SENSE instance created by propagate
    vlan: int | None                                  # VLAN allocated by SENSE


@dataclass
class Reservation:
    """A reserve of one or more offers, committed or released as a whole (slide 19: one hold for the whole group)."""

    reserve_id: str
    query_id: str
    reserved_offers: list[ReservedOffer]
    expires_at: datetime                              # an uncommitted reservation is void after this
    state: Literal["reserved", "committed", "released", "expired"] = "reserved"   # released / expired: every offer
                                                      # given back, by a release or by the expiry sweep
    commitment_ids: dict[str, str] = field(default_factory=dict)       # offer_id → commitment_id, written by commit
    released: set[str] = field(default_factory=set)                    # offer_ids given back (step 5b)

    @property
    def held(self) -> list[ReservedOffer]:
        """The reserved offers not released yet, in reserve order."""
        return [o for o in self.reserved_offers if o.offer_id not in self.released]

    def is_expired(self, now: datetime) -> bool:
        """Void for commit and modify: swept already, or uncommitted and past expires_at (not swept yet)."""
        return self.state == "expired" or (self.state == "reserved" and now >= self.expires_at)

    def mark_released(self, offer_ids: list[str], done: Literal["released", "expired"] = "released") -> None:
        """Record these reserved offers as given back; once none is held, the reservation's state becomes ``done``."""
        self.released.update(offer_ids)
        if not self.held:
            self.state = done


@dataclass(frozen=True)
class Committed:
    """A commitment together with the reserved offer behind it (path, booking, SENSE instance, request)."""

    commitment: Commitment
    reserve_id: str
    reserved_offer: ReservedOffer


@dataclass(frozen=True)
class Answered:
    """A request that succeeded and the reply it got, keyed in AgentContext.answered by (verb, request id)."""

    request: Msg
    response: Msg


@dataclass(frozen=True)
class AlertKey:
    """An observed condition, independent of delivery id and observation timestamp."""

    source: str
    kind: str
    link_id: str | None
    flow_id: str | None
    start: datetime
    end: datetime | None
    measured_gbps: float | None


@dataclass(frozen=True)
class RepairConditions:
    """Inputs to a repair decision; observation timestamps deliberately do not participate in equality."""

    cause: Cause
    links: tuple[str, ...]
    commitment: Commitment
    request: TransferRequest
    remaining_bytes: int
    cap_gbps: float | None
    paths: tuple[Path, ...]
    # (directed link, slot, up, capacity without us, our bookings)
    capacity: tuple[tuple[str, int, bool, float, float], ...]
    # Borrow also depends on each possible lender's progress and eligibility.
    lenders: tuple[tuple[Commitment, TransferRequest, int, bool], ...]


@dataclass(frozen=True)
class FailedRepair:
    conditions: RepairConditions
    retry_after: datetime


@dataclass
class AgentContext:
    cfg: NetAgentConfig
    topology: Topology
    ledger: CapacityLedger
    telemetry: TelemetrySource
    sense: SenseAdapter
    rate_model: RateModel
    flows: FlowSource                                                 # transfer progress (step 7, provisional)
    offer_book: dict[str, QueriedOffer] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    commitments: dict[str, Commitment] = field(default_factory=dict)
    orphans: dict[str, str] = field(default_factory=dict)            # instance_id → its booking, kept until cancelled
    expired_queries: set[str] = field(default_factory=set)            # query_ids whose offers were dropped
    answered: dict[tuple[str, str], Answered] = field(default_factory=dict)   # (verb, request id) → Answered
    progress_seen: dict[str, FlowProgress] = field(default_factory=dict)       # instance_id → last reading
    failed_repairs: dict[str, FailedRepair] = field(default_factory=dict)
    reported_unresolved: dict[str, DeviationReport] = field(default_factory=dict)
    processed_alerts: dict[AlertKey, datetime] = field(default_factory=dict)  # successful alerts → cache expiry
    _seq: dict[str, Iterator[int]] = field(init=False, repr=False, default_factory=lambda: defaultdict(lambda: count(1)))

    def new_id(self, prefix: str) -> str:
        """A fresh id such as "rsv-1", unique within this agent; each prefix counts from 1."""
        return f"{prefix}-{next(self._seq[prefix])}"

    def forget_repair(self, commitment_id: str) -> None:
        """A resolved, changed or released commitment starts a new repair episode."""
        self.failed_repairs.pop(commitment_id, None)
        self.reported_unresolved.pop(commitment_id, None)

    def committed(self) -> list[Committed]:
        """Every commitment still held, in reservation order."""
        return [Committed(self.commitments[r.commitment_ids[o.offer_id]], r.reserve_id, o)
                for r in self.reservations.values() if r.state == "committed"
                for o in r.held if o.offer_id in r.commitment_ids]
