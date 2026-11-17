"""Network topology: nodes, links, candidate paths.

The topology describes physical links (undirected, e.g. fiber L2 connecting esnet-chi and esnet-atl).
Links are full duplex, with the full capacity available in each direction, so internally every
physical link is split into two **directed links**, and the ledger also books per directed link:
saturating A→B does not affect B→A.

Directed link ids look like ``L2:esnet-chi>esnet-atl``; a path is a tuple of directed link ids.
"""

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, PositiveFloat, model_validator


class LinkSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    a: str
    b: str
    capacity_gbps: PositiveFloat   # configured capacity in each direction (full duplex, assumed symmetric); from the slide-14 WfPlatform static snapshot, used to initialize the ledger


class TopologySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    nodes: list[str]
    links: list[LinkSpec]

    @model_validator(mode="after")
    def _consistent(self):
        if len(set(self.nodes)) != len(self.nodes):
            raise ValueError("duplicate node id")
        if len({link.id for link in self.links}) != len(self.links):
            raise ValueError("duplicate link id")
        for link in self.links:
            if link.a == link.b:
                raise ValueError(f"link {link.id} is a self-loop")
            if not {link.a, link.b} <= set(self.nodes):
                raise ValueError(f"link {link.id} references an unknown node")
        return self


@dataclass(frozen=True)
class DirectedLink:
    id: str            # "L2:esnet-chi>esnet-atl"
    link_id: str       # physical link "L2"
    src: str
    dst: str
    capacity_gbps: float


Path = tuple[str, ...]  # sequence of directed link ids


class Topology:
    def __init__(self, spec: TopologySpec):
        self.nodes = list(spec.nodes)
        self.links: dict[str, DirectedLink] = {}
        self._out: dict[str, list[DirectedLink]] = {n: [] for n in spec.nodes}
        for s in spec.links:
            for src, dst in ((s.a, s.b), (s.b, s.a)):
                d = DirectedLink(f"{s.id}:{src}>{dst}", s.id, src, dst, s.capacity_gbps)
                self.links[d.id] = d
                self._out[src].append(d)

    @classmethod
    def from_dict(cls, d: dict) -> "Topology":
        return cls(TopologySpec.model_validate(d))

    def paths(self, src: str, dst: str, k: int) -> list[Path]:
        """Loop-free paths src → dst, sorted by (hop count, link ids), at most k; an empty list if there is none.

        Enumerates every loop-free path, which only suits demo-sized topologies; switch to Yen's
        k-shortest paths once the topology grows.
        """
        for n in (src, dst):
            if n not in self._out:
                raise KeyError(f"unknown node {n!r}")
        found: list[Path] = []

        def walk(node: str, visited: set[str], path: list[str]) -> None:
            if node == dst:
                found.append(tuple(path))
                return
            for d in self._out[node]:
                if d.dst not in visited:
                    walk(d.dst, visited | {d.dst}, path + [d.id])

        walk(src, {src}, [])
        return sorted(found, key=lambda p: (len(p), p))[:k]
