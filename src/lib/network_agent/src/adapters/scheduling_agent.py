"""Provisional contracts with the scheduling agent; production callers must supply real implementations."""

from datetime import datetime
from typing import Protocol

from ..models.schemas import RepairDecision, RepairProposal, TransferRequest


# SchedulingAgent should provide this API
class RepairCoordinator(Protocol):
    def choose(self, proposals: list[RepairProposal], now: datetime) -> RepairDecision | None:
        """
        - Return a decision (None rejects all), without changing network reservations.
        - An asynchronous transport must arrange a fresh invocation and revalidation after its reply;
        - this interface does not leave an approval pending or default to acceptance.
        """
        ...


class SciNetDemandSource(Protocol):
    """PLACEHOLDER for the forecast's part B (SciNet traffic forecast); nothing calls it yet. The scheduling
    agent infers, from the dependencies between workflows, which SciNet transfers are likely to come and
    when. The forecast would map them onto links × slots (their paths are not known yet), keep them apart
    from ``observed`` (they are SciNet's own traffic, not background), and use them to keep headroom in
    planning and admission; when they would not fit, it would report back to the scheduling agent."""

    def future_demand(self, now: datetime, until: datetime) -> list[TransferRequest]:
        """Transfers expected to be requested before ``until``; their windows say roughly when."""
        ...
