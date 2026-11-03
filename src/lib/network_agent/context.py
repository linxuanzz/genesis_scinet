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
"""

from collections import defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from typing import Literal

from .config import NetAgentConfig
from .estimate import RateModel
from .ledger import CapacityLedger
from .placement import Placement
from .schemas import Commitment, Msg, ServiceIntent, TransferRequest
from .sense import SenseAdapter
from .telemetry import TelemetrySource
from .topology import Topology


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
    items: list[ReservedOffer]
    expires_at: datetime                              # an uncommitted reservation is void after this
    state: Literal["reserved", "committed", "released", "expired"] = "reserved"   # released / expired: every item
                                                      # given back, by a release or by the expiry sweep
    commitment_ids: dict[str, str] = field(default_factory=dict)       # offer_id → commitment_id, written by commit
    released: set[str] = field(default_factory=set)                    # offer_ids given back (step 5b)

    @property
    def held(self) -> list[ReservedOffer]:
        """The items not released yet, in reserve order."""
        return [i for i in self.items if i.offer_id not in self.released]

    def is_expired(self, now: datetime) -> bool:
        """Void for commit and modify: swept already, or uncommitted and past expires_at (not swept yet)."""
        return self.state == "expired" or (self.state == "reserved" and now >= self.expires_at)

    def mark_released(self, offer_ids: list[str], done: Literal["released", "expired"] = "released") -> None:
        """Record these items as given back; once none is held, the reservation's state becomes ``done``."""
        self.released.update(offer_ids)
        if not self.held:
            self.state = done


@dataclass(frozen=True)
class Answered:
    """A request that succeeded and the reply it got, keyed in AgentContext.answered by (verb, request id)."""

    request: Msg
    response: Msg


@dataclass
class AgentContext:
    cfg: NetAgentConfig
    topology: Topology
    ledger: CapacityLedger
    telemetry: TelemetrySource
    sense: SenseAdapter
    rate_model: RateModel
    offer_book: dict[str, QueriedOffer] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    commitments: dict[str, Commitment] = field(default_factory=dict)
    orphans: dict[str, str] = field(default_factory=dict)            # instance_id → its booking, kept until cancelled
    expired_queries: set[str] = field(default_factory=set)            # query_ids whose offers were dropped
    answered: dict[tuple[str, str], Answered] = field(default_factory=dict)   # (verb, request id) → Answered
    _seq: dict[str, Iterator[int]] = field(init=False, repr=False, default_factory=lambda: defaultdict(lambda: count(1)))

    def new_id(self, prefix: str) -> str:
        """A fresh id such as "rsv-1", unique within this agent; each prefix counts from 1."""
        return f"{prefix}-{next(self._seq[prefix])}"
