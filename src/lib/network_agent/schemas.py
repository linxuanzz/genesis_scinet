"""Messages between the scheduling agent and the network agent (slides 6, 7, 19).

This file holds the messages of the planning loop query → reserve → commit, telemetry samples
(step 3a) and SENSE messages (step 3b); other messages are added in the step that first needs them
(modify / release → step 5b, repaired / at_risk → step 7, TransferRecord → step 9).

All messages are immutable pydantic models that reject unknown fields: agents exchange JSON, so a
bad message is stopped at the door and never reaches the ledger. Validation only covers "format and
internal consistency", not "can it be satisfied" — the latter is find_placements' job.
"""

from datetime import datetime
from typing import Literal

from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, NonNegativeFloat, NonNegativeInt, PositiveFloat, PositiveInt, model_validator,
)


class Msg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _unique(ids: list[str], what: str) -> None:
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        raise ValueError(f"duplicate {what}: {dup}")


def _check_profile(profile: list["RateSegment"]) -> None:
    if not profile:
        raise ValueError("rate_profile must not be empty")
    for a, b in zip(profile, profile[1:]):
        if b.start < a.end:
            raise ValueError("rate_profile segments must be sorted and non-overlapping")


# ── query ────────────────────────────────────────────────────────────────

class TimeWindow(Msg):
    earliest_start: AwareDatetime
    latest_finish: AwareDatetime

    @model_validator(mode="after")
    def _ordered(self):
        if self.earliest_start >= self.latest_finish:
            raise ValueError("earliest_start must be before latest_finish")
        return self


class TransferRequest(Msg):
    """The requirement of one transfer, not a route: "these bytes must start after t1 and finish before t2" (slide 6)."""

    id: str
    workflow_id: str
    priority: NonNegativeInt                          # higher means more important
    src: str                                          # site/endpoint id, a node in the topology
    dst: str
    bytes: PositiveInt
    is_estimate: bool                                 # True: the size is an estimate and will be refined at runtime
    divisible: bool                                   # whether it may be split into several segments/paths
    window: TimeWindow
    min_useful_rate_gbps: PositiveFloat | None = None  # offers below this rate are useless (slide 19)

    @model_validator(mode="after")
    def _distinct_ends(self):
        if self.src == self.dst:
            raise ValueError("src and dst must differ")
        return self


class QueryRequest(Msg):
    """Asks about one bundle at a time; read-only, reserves nothing (slide 6)."""

    query_id: str
    bundle: list[TransferRequest]
    mode: Literal["all_or_nothing", "best_subset"]

    @model_validator(mode="after")
    def _bundle_ok(self):
        if not self.bundle:
            raise ValueError("bundle must not be empty")
        _unique([t.id for t in self.bundle], "transfer id")
        return self


class RateSegment(Msg):
    """Transfer at gbps over the time range [start, end)."""

    start: AwareDatetime
    end: AwareDatetime
    gbps: PositiveFloat

    @model_validator(mode="after")
    def _ordered(self):
        if self.start >= self.end:
            raise ValueError("segment start must be before end")
        return self


class Offer(Msg):
    """One feasible option. The network agent only lists the possibilities; it does not choose for the scheduling agent (slide 7)."""

    offer_id: str
    transfer_id: str
    rate_profile: list[RateSegment]                   # sorted by time, non-overlapping; gaps are allowed
    predicted_finish_p50: AwareDatetime
    predicted_finish_p95: AwareDatetime
    blocked_by: Literal["own_commitment", "background_traffic"] | None = None  # why no better offer was given

    @property
    def start(self) -> datetime:
        return self.rate_profile[0].start

    @model_validator(mode="after")
    def _consistent(self):
        _check_profile(self.rate_profile)
        if not self.start <= self.predicted_finish_p50 <= self.predicted_finish_p95:
            raise ValueError("need start <= predicted_finish_p50 <= predicted_finish_p95")
        return self


class RejectReason(Msg):
    cause: Literal["no_path", "no_capacity", "beyond_horizon", "below_min_useful_rate"]
    detail: str
    when: AwareDatetime | None = None                 # if set: the earliest time capacity may be available


class TransferQuery(Msg):
    """The query result for one transfer in the bundle (slide 19: feasible | infeasible | unreachable)."""

    transfer_id: str
    status: Literal["feasible", "infeasible", "unreachable"]
    offers: list[Offer] = []
    reason: RejectReason | None = None

    @model_validator(mode="after")
    def _consistent(self):
        if self.status == "feasible":
            if not self.offers or self.reason is not None:
                raise ValueError("feasible needs offers and no reason")
        elif self.offers or self.reason is None:
            raise ValueError(f"{self.status} needs a reason and no offers")
        if any(o.transfer_id != self.transfer_id for o in self.offers):
            raise ValueError("offer.transfer_id must match")
        _unique([o.offer_id for o in self.offers], "offer id")
        return self


class QueryResponse(Msg):
    query_id: str
    mode: Literal["all_or_nothing", "best_subset"]
    results: list[TransferQuery]
    valid_until: AwareDatetime                        # the offers can be reserved until then (step 5b)

    @property
    def admissible(self) -> bool:
        """all_or_nothing: admissible only if every transfer is feasible; best_subset: at least one is feasible."""
        ok = [r.status == "feasible" for r in self.results]
        return all(ok) if self.mode == "all_or_nothing" else any(ok)


# ── reserve (hold in the slides) / commit ─────────────────────────────────

class ReserveRequest(Msg):
    """Tentatively reserve the chosen offers; released automatically if not committed before the TTL expires (slide 19)."""

    request_id: str                                   # for idempotent handling of duplicate requests (step 5b)
    query_id: str
    offer_ids: list[str]
    ttl_seconds: PositiveInt | None = None            # None → use reserve_ttl_seconds from the config

    @model_validator(mode="after")
    def _offers_ok(self):
        if not self.offer_ids:
            raise ValueError("offer_ids must not be empty")
        _unique(self.offer_ids, "offer id")
        return self


class ReserveAck(Msg):
    reserve_id: str
    offer_ids: list[str]
    expires_at: AwareDatetime


class CommitRequest(Msg):
    request_id: str
    reserve_id: str


class EndpointBinding(Msg):
    """The endpoints the WMS must use when moving data; without them the bytes take the default route (slides 5, 19)."""

    transfer_id: str
    src_uri: str
    dst_uri: str
    vlan: int
    interface: str | None = None                      # host NIC; SENSE only returns the VLAN, so this comes from
                                                      # site configuration (None until one supplies it)

    @model_validator(mode="after")
    def _vlan_range(self):
        if not 1 <= self.vlan <= 4094:
            raise ValueError("vlan must be in 1..4094")
        return self


class Commitment(Msg):
    """A commitment = one transfer placed on some circuit; several commitments may share a circuit (slide 24)."""

    commitment_id: str
    transfer_id: str
    workflow_id: str
    circuit_id: str
    rate_profile: list[RateSegment]
    binding: EndpointBinding


class CommitAck(Msg):
    reserve_id: str
    commitments: list[Commitment]


# ── release (step 5b) ─────────────────────────────────────────────────────

class ReleaseRequest(Msg):
    """Give back a reservation, committed or not: all of it, or only some of its offers (e.g. a transfer
    that finished early while the rest of the group keeps its circuits)."""

    request_id: str
    reserve_id: str
    offer_ids: list[str] | None = None                # None → every offer still held

    @model_validator(mode="after")
    def _offers_ok(self):
        if self.offer_ids is not None:
            if not self.offer_ids:
                raise ValueError("offer_ids must not be empty; leave it out to release everything")
            _unique(self.offer_ids, "offer id")
        return self


class ReleaseAck(Msg):
    reserve_id: str
    offer_ids: list[str]                              # released by this request


# ── modify (step 5b) ──────────────────────────────────────────────────────

class ModifyRequest(Msg):
    """Change the rate and/or time range of one reserved or committed offer, on the same path and circuit.
    Moving to another path is not a modify: reserve the new one, then release the old (make-before-break)."""

    request_id: str
    reserve_id: str
    offer_id: str
    rate_profile: list[RateSegment]                   # the offer's new profile, replacing the old one

    @model_validator(mode="after")
    def _profile_ok(self):
        _check_profile(self.rate_profile)
        return self


class ModifyAck(Msg):
    reserve_id: str
    offer_id: str
    rate_profile: list[RateSegment]                   # now in effect
    commitment: Commitment | None = None              # the updated commitment, if the offer was committed


class ErrorResponse(Msg):
    """The reply when validation or execution fails (the exit for failed validation)."""

    request_id: str
    code: Literal["invalid_request", "not_found", "expired", "conflict", "sense_failure"]
    detail: str


# ── telemetry → network agent ─────────────────────────────────────────────

class LinkSample(Msg):
    """A telemetry observation of one directed link over [start, end) (slide 10: the network agent
    subscribes to link state and capacity).

    Semantics of ``available_gbps``: the capacity available **when our own bookings are not counted**
    (= capacity − background traffic / others' reservations), i.e. the ledger's observed. The ledger
    computes available = observed − own from it; if a data source's number already has our own
    bookings deducted, that source's adapter must add them back, or they would be deducted twice.

    Values for future time ranges are what the data source "currently believes" (e.g. reservations
    others have registered), not a traffic forecast.
    """

    link_id: str                      # directed link id, e.g. "L2:esnet-chi>esnet-atl"
    start: AwareDatetime
    end: AwareDatetime
    up: bool
    available_gbps: NonNegativeFloat
    sampled_at: AwareDatetime
    valid_until: AwareDatetime        # after this time the corresponding ledger values are stale and need refreshing
    source: str                       # "telemetry" | "sense" | "mock" | ...

    @model_validator(mode="after")
    def _consistent(self):
        if self.start >= self.end:
            raise ValueError("start must be before end")
        if self.valid_until < self.sampled_at:
            raise ValueError("valid_until must not precede sampled_at")
        if not self.up and self.available_gbps > 0:
            raise ValueError("a down link has no available capacity")
        return self


# ── network agent ↔ SENSE-O / NDT (slide 8) ───────────────────────────────
# Fields follow the DNC of SENSE-O Intent API 2.0.4, with two simplifications:
# one connection with exactly two endpoints; bandwidth as int Mbps (SENSE expects a Mbps string,
# converted by the real adapter).

QosClass = Literal["guaranteedCapped", "softCapped", "anyAvailable", "bestEffort"]


class Terminal(Msg):
    uri: str                                          # SENSE endpoint URI, e.g. "urn:ogf:network:anl.gov:..."
    vlan_tag: str = "any"                             # "any": allocated by SENSE


class ServiceIntent(Msg):
    """A request for one SENSE service instance: a constant-bandwidth connection between two endpoints over a time range.

    An intent has a single bandwidth value and corresponds to a circuit in slide 24; how a commitment
    with several rate segments maps onto circuits is up to place_on_circuit / compile_intent in step 5a.
    """

    alias: str                                        # a name we choose, for tracing on the SENSE side
    terminals: list[Terminal]
    capacity_mbps: PositiveInt                        # bandwidth.capacity
    qos_class: QosClass                               # bandwidth.qos_class
    start: AwareDatetime                              # schedule.start
    end: AwareDatetime                                # schedule.end
    path_inclusion: list[str] = []                    # path_tprofile.inclusion_list; directed link ids here,
                                                      # which the real adapter must map to SENSE Path URIs

    @model_validator(mode="after")
    def _consistent(self):
        if len(self.terminals) != 2 or self.terminals[0].uri == self.terminals[1].uri:
            raise ValueError("need exactly two distinct terminals")
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class ServiceState(Msg):
    """Instance state returned by SENSE. Two phases: propagate → reserved (resources held, no configuration
    pushed), commit → committed."""

    instance_id: str                                  # SENSE's siUUID
    alias: str
    state: Literal["reserved", "committed", "cancelled"]
    vlan: int | None                                  # VLAN allocated by SENSE; needed by EndpointBinding
    changed_at: AwareDatetime
