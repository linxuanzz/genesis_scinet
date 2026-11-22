"""Provisional contract with the transfer endpoint, with a mock; production callers must supply a real implementation."""

from datetime import datetime
from typing import Protocol

from ..sim.sim import MockNetwork

"""
- Moves a running transfer onto another circuit.
- SENSE only sets up and tears down circuits;
- rebinding the flow (e.g. to the new VLAN) happens at the transfer endpoint, which alone can confirm the move, so
the old circuit is released only after that confirmation.
"""
class TransferController(Protocol):
    def switch(self, old_instance: str, new_instance: str, now: datetime) -> bool:
        """True confirms the transfer/binding has moved. False or an exception must leave the old binding active.

        Implementations must resolve an uncertain handoff internally before returning; the caller releases
        the old circuit only on True. This confirms execution, not long-term throughput recovery.
        """
        ...


class MockTransferController:
    def __init__(self, network: MockNetwork):
        self.network = network

    def switch(self, old_instance: str, new_instance: str, now: datetime) -> bool:
        if old_instance in self.network._flows:
            self.network.switch_flow(old_instance, new_instance, now)
        return True
