"""Provisional contract with the scheduling agent; production callers must supply a real implementation."""

from datetime import datetime
from typing import Protocol

from ..models.schemas import RepairDecision, RepairProposal

# SchedulingAgent should provide this API
class RepairCoordinator(Protocol):
    def choose(self, proposals: list[RepairProposal], now: datetime) -> RepairDecision | None:
        """
        - Return a decision (None rejects all), without changing network reservations.
        - An asynchronous transport must arrange a fresh invocation and revalidation after its reply;
        - this interface does not leave an approval pending or default to acceptance.
        """
        ...
