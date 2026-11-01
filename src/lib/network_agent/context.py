"""Runtime environment shared by the three graphs (the LangGraph runtime context).

A graph's state only records the work of "this one execution". Long-lived objects shared by all
requests — the ledger, the topology, external interfaces, and the books of what we have quoted,
reserved and committed — live in the context instead: the caller builds it once and passes it on
every invoke (by design, the ledger stays out of state).

The three books form a chain, each entry pointing back to the previous one by id:

    offer_book     offer_id      → QuotedOffer   written by quote's respond
    reservations   reserve_id    → Reservation   written by reserve (step 5a)
    commitments    commitment_id → Commitment    written by commit (step 5a)
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count
from typing import Literal

from .config import NetAgentConfig
from .estimate import RateModel
from .ledger import CapacityLedger
from .placement import Placement
from .schemas import Commitment, ServiceIntent, TransferRequest
from .sense import SenseAdapter
from .telemetry import TelemetrySource
from .topology import Topology


@dataclass(frozen=True)
class QuotedOffer:
    """What we remember about an offer we quoted. The scheduling agent only sees the Offer; the request it
    answers (needed later for the commitment's workflow_id) and the placement behind it (path, rule) stay here."""

    quote_id: str
    request: TransferRequest
    placement: Placement


@dataclass(frozen=True)
class ReservedOffer:
    """One offer inside a reservation: the ledger booking and the SENSE instance that hold it."""

    offer_id: str
    placement: Placement                              # what was actually booked (may differ from the quote once
                                                      # the alternate-path hook exists); gives the commitment's rate
    booking_id: str                                   # ledger booking; pending until commit
    intent: ServiceIntent                             # what was sent to SENSE; its terminals become the EndpointBinding
    instance_id: str                                  # SENSE instance created by propagate
    vlan: int | None                                  # VLAN allocated by SENSE


@dataclass
class Reservation:
    """A reserve of one or more offers, committed or released as a whole (slide 19: one hold for the whole group)."""

    reserve_id: str
    quote_id: str
    items: list[ReservedOffer]
    expires_at: datetime                              # an uncommitted reservation is void after this
    state: Literal["reserved", "committed"] = "reserved"


@dataclass
class AgentContext:
    cfg: NetAgentConfig
    topology: Topology
    ledger: CapacityLedger
    telemetry: TelemetrySource
    sense: SenseAdapter
    rate_model: RateModel
    offer_book: dict[str, QuotedOffer] = field(default_factory=dict)
    reservations: dict[str, Reservation] = field(default_factory=dict)
    commitments: dict[str, Commitment] = field(default_factory=dict)
    _seq: Iterator[int] = field(init=False, repr=False, default_factory=lambda: count(1))

    def new_id(self, prefix: str) -> str:
        """A fresh id such as "rsv-1", unique within this agent."""
        return f"{prefix}-{next(self._seq)}"
