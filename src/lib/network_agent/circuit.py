"""From placements to SENSE circuits (slide 24): which circuit carries an offer, and the ServiceIntent that asks SENSE for it.

Step 5a keeps the simplest mapping: every reserved offer gets a new circuit of its own, i.e. one
ServiceIntent and one SENSE instance. This works because every offer so far has a single constant
rate (one RateSegment), which is exactly what one intent can express.
"""

from .placement import Placement
from .schemas import QosClass, ServiceIntent, Terminal

MBPS_PER_GBPS = 1000

# A reservation must be guaranteed (others cannot take it) and capped at what the ledger booked
# (we cannot take more), otherwise the per-link ledger no longer matches the network. This is part of
# the meaning of a reservation, not a tunable parameter.
QOS_CLASS: QosClass = "guaranteedCapped"


def place_on_circuit(p: Placement) -> Placement:
    """Decide how a quoted placement is carried. Step 5a: unchanged, on a new circuit of its own.

    Extension hooks (not implemented):
    - warm-circuit reuse: put the transfer on an existing circuit with spare capacity on the same path
      and time range instead of creating a new one (slide 24);
    - alternate path: if the quoted path has filled up since the quote, honour the same offer (same start
      and rate) on another path that the quote deduplicated away; invisible to the scheduling agent;
    - priority / preemption: make room for a higher-priority transfer by moving or shrinking lower ones.
    """
    return p


def compile_intent(p: Placement, src: str, dst: str, alias: str) -> ServiceIntent:
    """One placement → one SENSE intent: constant bandwidth over [start, end) between src and dst along the
    placement's path.

    Terminal URIs are topology node ids here; a real SENSE adapter maps them to SENSE endpoint URIs.
    """
    return ServiceIntent(alias=alias, terminals=[Terminal(uri=src), Terminal(uri=dst)],
                         capacity_mbps=round(p.gbps * MBPS_PER_GBPS), qos_class=QOS_CLASS,
                         start=p.start, end=p.end, path_inclusion=list(p.path))
