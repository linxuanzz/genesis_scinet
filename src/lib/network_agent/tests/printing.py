"""Printing helpers shared by the demos (step 4 query, steps 5a / 5b conversations with graph A)."""

from datetime import timedelta

from ..graphs.protocol import build_protocol_graph
from ..schemas import (
    CommitAck, CommitRequest, ErrorResponse, ModifyAck, ModifyRequest, QueryRequest, QueryResponse, ReleaseAck,
    ReleaseRequest, ReserveAck, ReserveRequest,
)
from .helpers import MAIN, make_ctx, t

LEDGER_SPAN = (t(9), t(15))                       # time range of the printed ledger


def sec(s):
    return timedelta(seconds=s)


def hops(topology, path):
    """Directed link id sequence → 'anl-n02 ─L1→ esnet-atl ─L2→ ...'"""
    links = [topology.links[d] for d in path]
    return links[0].src + "".join(f" ─{d.link_id}→ {d.dst}" for d in links)


def print_network(title, net):
    """Title banner, then the simulated network: nodes, links, background traffic, outages."""
    topo = net.topology
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
    print("Nodes:", ", ".join(topo.nodes))
    print("Links (physical; capacity is per direction):")
    printed = set()
    for d in topo.links.values():                           # print each physical link once, in its defined a → b direction
        if d.link_id not in printed:
            printed.add(d.link_id)
            print(f"  {d.link_id}: {d.src} — {d.dst}   {d.capacity_gbps:g} Gbps")
    print("Background traffic:")
    for link, ivs in net._background.items():
        for iv in ivs:
            print(f"  {link}   {iv.start:%H:%M}–{iv.end:%H:%M}   {iv.gbps:g} Gbps")
    print("Outages:", [f"{link} {iv.start:%H:%M}–{iv.end:%H:%M}" for link, ivs in net._outages.items() for iv in ivs] or "none")


# ── a conversation with graph A ───────────────────────────────────────────

class Session:
    """One network agent (graph A + its context) and a printer for everything sent to it."""

    def __init__(self, title, net):
        self.net, self.ctx, self.graph = net, make_ctx(net), build_protocol_graph()
        print_network(title, net)
        self.print_state(t(9))

    def send(self, verb, msg, now):
        print(f"\n{'─' * 100}\n{now:%H:%M:%S}  scheduling agent → network agent: {verb}")
        print_request(msg)
        out = self.graph.invoke({"verb": verb, "raw": msg.model_dump(), "now": now}, context=self.ctx)
        swept = out.get("swept")
        if swept and (swept.expired or swept.stuck or swept.orphans or swept.queries):
            print(f"  (sweep before the branch: expired reservations {swept.expired}, still stuck {swept.stuck}, "
                  f"orphans cancelled {swept.orphans}, queries dropped {swept.queries})")
        print("network agent → scheduling agent:" + ("   (replayed from the cache; nothing ran)"
                                                      if out.get("replayed") else ""))
        print_response(out["response"], self.ctx)
        self.print_state(now)
        return out["response"]

    def event(self, text):
        print(f"\n{'─' * 100}\n!! {text}")

    def print_state(self, now):
        ctx = self.ctx
        print(f"\n  Ledger on the main path at {now:%H:%M:%S} (Gbps; observed = what telemetry last reported, "
              "own = our bookings; stale = due for a refresh):")
        for link in MAIN:
            print(f"    {link}")
            for a, b, obs, own, avail, stale in ledger_runs(ctx.ledger, link, *LEDGER_SPAN, now):
                print(f"      {a:%H:%M}–{b:%H:%M}   observed {obs:>5g}{' (stale)' if stale else '        '}"
                      f"   own {own:>5g}   available {avail:>5g}")
        items = [(r, i) for r in ctx.reservations.values() for i in r.items]
        print("  Reservations:" + ("" if items else " none"))
        for r, i in items:
            p = i.placement
            booking = "given back" if i.offer_id in r.released else f"= {ctx.ledger.booking(i.booking_id).state}"
            print(f"    {r.reserve_id} ({r.state}, expires {r.expires_at:%H:%M:%S})  {i.offer_id}: "
                  f"{p.start:%H:%M:%S}–{p.end:%H:%M:%S} @ {p.gbps:g} Gbps   booking {i.booking_id} {booking}")
        states = list(ctx.sense._states.values())
        print("  SENSE instances:" + ("" if states else " none"))
        for s in states:
            held = self.net._ours.get(s.instance_id)
            where = f"   holds {held[1].gbps:g} Gbps {held[1].start:%H:%M:%S}–{held[1].end:%H:%M:%S}" if held else ""
            print(f"    {s.instance_id}  {s.state:<9}  vlan {s.vlan}  alias {s.alias}{where}")


def ledger_runs(ledger, link, start, end, now):
    """One link over [start, end), merging adjacent slots with equal values:
    [(start, end, observed, own, available, stale)]."""
    runs = []
    for i in ledger.slots_covering(start, end):
        row = (ledger.observed(link, i).gbps, ledger.own(link, i), ledger.available(link, i), ledger.is_stale(link, i, now))
        a, b = ledger.slot_start(i), ledger.slot_start(i + 1)
        if runs and runs[-1][2:] == row:
            runs[-1] = (runs[-1][0], b, *row)
        else:
            runs.append((a, b, *row))
    return runs


def print_request(msg):
    if isinstance(msg, QueryRequest):
        print(f"  query_id {msg.query_id}, mode {msg.mode}")
        for x in msg.bundle:
            print(f"  {x.id} ({x.workflow_id}): {x.src} → {x.dst}, {x.bytes / 1e12:g} TB, "
                  f"window {x.window.earliest_start:%H:%M}–{x.window.latest_finish:%H:%M}")
    elif isinstance(msg, ReserveRequest):
        print(f"  request_id {msg.request_id}, query_id {msg.query_id}, offers {msg.offer_ids}")
    elif isinstance(msg, CommitRequest):
        print(f"  request_id {msg.request_id}, reserve_id {msg.reserve_id}")
    elif isinstance(msg, ReleaseRequest):
        print(f"  request_id {msg.request_id}, reserve_id {msg.reserve_id}, offers {msg.offer_ids or 'all held'}")
    elif isinstance(msg, ModifyRequest):
        print(f"  request_id {msg.request_id}, reserve_id {msg.reserve_id}, offer {msg.offer_id} → "
              + ", ".join(f"{s.start:%H:%M:%S}–{s.end:%H:%M:%S} @ {s.gbps:g} Gbps" for s in msg.rate_profile))


def print_response(resp, ctx):
    if isinstance(resp, ErrorResponse):
        print(f"  ERROR {resp.code}: {resp.detail}")
    elif isinstance(resp, QueryResponse):
        print(f"  valid until {resp.valid_until:%H:%M:%S}")
        for r in resp.results:
            if r.status != "feasible":
                print(f"  {r.transfer_id}: {r.status} ({r.reason.cause}: {r.reason.detail})")
            for o in r.offers:
                s, q = o.rate_profile[0], ctx.offer_book.get(o.offer_id)   # path is not sent; shown from offer_book
                path = f"   [{hops(ctx.topology, q.placement.path)}]" if q else ""
                print(f"  {o.offer_id}: {s.start:%H:%M} @ {s.gbps:>5g} Gbps → {o.predicted_finish_p50:%H:%M:%S}"
                      f"   blocked_by={o.blocked_by}{path}")
    elif isinstance(resp, ReserveAck):
        print(f"  ReserveAck {resp.reserve_id}: offers {resp.offer_ids}, expires {resp.expires_at:%H:%M:%S}")
    elif isinstance(resp, CommitAck):
        print(f"  CommitAck {resp.reserve_id}:")
        for c in resp.commitments:
            print_commitment(c)
    elif isinstance(resp, ReleaseAck):
        print(f"  ReleaseAck {resp.reserve_id}: released {resp.offer_ids}")
    elif isinstance(resp, ModifyAck):
        seg = resp.rate_profile[0]
        print(f"  ModifyAck {resp.reserve_id}/{resp.offer_id}: now {seg.start:%H:%M:%S}–{seg.end:%H:%M:%S} @ {seg.gbps:g} Gbps")
        if resp.commitment:
            print_commitment(resp.commitment)


def print_commitment(c):
    seg, b = c.rate_profile[0], c.binding
    print(f"    {c.commitment_id}: {c.transfer_id} ({c.workflow_id}) on circuit {c.circuit_id}, "
          f"{seg.start:%H:%M:%S}–{seg.end:%H:%M:%S} @ {seg.gbps:g} Gbps")
    print(f"      binding: {b.src_uri} → {b.dst_uri}, vlan {b.vlan}, interface {b.interface}")
