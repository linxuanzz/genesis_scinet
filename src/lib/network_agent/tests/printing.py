"""Printing helpers shared by the demos (step 4 query, steps 5a / 5b conversations with graph A, step 7 runs of graph B)."""

from datetime import timedelta

from ..src.graphs.protocol.protocol import build_protocol_graph
from ..src.graphs.runtime.runtime import build_runtime_graph
from ..src.models.schemas import (CommitAck, CommitRequest, ErrorResponse, ModifyAck, ModifyRequest, QueryRequest,
                                  QueryResponse, ReleaseAck, ReleaseRequest, ReserveAck, ReserveRequest)
from .helpers import MAIN, make_ctx, t

LEDGER_SPAN = (t(9), t(15))                       # time range of the printed ledger
OFFER_STRATEGY_LABELS = {
    "earliest_start": "Earliest start on this path",
    "max_rate": "Highest rate on this path",
    "min_rate": "Lowest rate meeting deadline on this path",
}


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
        rows = [(r, o) for r in ctx.reservations.values() for o in r.reserved_offers]
        print("  Reservations:" + ("" if rows else " none"))
        for r, o in rows:
            p = o.placement
            booking = "given back" if o.offer_id in r.released else f"= {ctx.ledger.booking(o.booking_id).state}"
            print(f"    {r.reserve_id} ({r.state}, expires {r.expires_at:%H:%M:%S})  {o.offer_id}: "
                  f"{p.start:%H:%M:%S}–{p.end:%H:%M:%S} @ {p.gbps:g} Gbps   booking {o.booking_id} {booking}")
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
                s, q = o.rate_profile[0], ctx.offer_book.get(o.offer_id)   # path and strategy are internal diagnostics
                strategy = f" [{OFFER_STRATEGY_LABELS[q.placement.strategy]}]" if q else ""
                path = f"   [{hops(ctx.topology, q.placement.path)}]" if q else ""
                print(f"  {o.offer_id}{strategy}: {s.start:%H:%M} @ {s.gbps:>5g} Gbps → {o.predicted_finish_p50:%H:%M:%S}"
                      f"   limited_by={o.limited_by}{path}")
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


# ── graph B runs (step 7) ─────────────────────────────────────────────────

class RuntimeSession:
    """One network agent with commitments in place, and a printer for graph B's runs on it."""

    def __init__(self, title, net, ctx):
        self.net, self.ctx, self.graph = net, ctx, build_runtime_graph()
        print_network(title, net)
        self.print_commitments()

    def event(self, text):
        print(f"\n{'─' * 100}\n!! {text}")

    def run(self, event, now):
        """Run graph B once; print the nodes it ran, what it found, judged and did; return the final state."""
        kind = event.get("kind") if isinstance(event, dict) else event.kind
        print(f"\n{'─' * 100}\n{now:%H:%M:%S}  graph B ← {kind}")
        nodes, out = [], {}
        for mode, chunk in self.graph.stream({"event": event, "now": now}, context=self.ctx,
                                             stream_mode=["updates", "values"]):
            if mode == "updates":
                nodes += list(chunk)
            else:
                out = chunk
        print("  path: " + " → ".join(nodes))
        if out.get("duplicate_event"):
            print("  duplicate alert: skipped before the forecast and detection")
        for d in out.get("deviations", []):
            p = d.progress
            branch = "flow: slow" if d.slow else "flow: overruns its reservation" if d.overrun else "link: damage ahead"
            rate = f", recent rate {d.recent_gbps:g} Gbps" if d.recent_gbps is not None else ""
            print(f"  deviation {d.commitment_id} ({branch}): cause {d.cause}, "
                  f"links {[link.split(':')[0] for link in d.links]}, sent {p.bytes_sent / 1e12:g} TB{rate}")
        for a in out.get("assessments", []):
            kept = a.finish_if_kept[1].strftime("%H:%M:%S") if a.finish_if_kept else "never"
            cap = f", capped at the {a.cap_gbps:g} Gbps still seen" if a.cap_gbps is not None else ""
            print(f"  assessment {a.commitment_id}: {a.remaining_bytes / 1e12:g} TB left; through by the reservation's "
                  f"end: {'yes' if a.finishes_in_reservation else 'no'}; at its rate past its end: {kept} (deadline "
                  f"{a.deadline:%H:%M}){cap}")
        for cid in out.get("retry_deferred", []):
            print(f"  {cid}: repair conditions unchanged; waiting to retry")
        for p in out.get("plans", []):
            print(f"  plan {p.assessment.commitment_id} (priority {p.assessment.priority}): {' → '.join(p.steps)}")
        print("network agent → scheduling agent:" + ("" if out.get("reports") else " nothing"))
        for cause, rs in out.get("reports", {}).items():
            for r in rs:
                seg = r.commitment.rate_profile[0]
                done = f"p95 {r.predicted_finish_p95:%H:%M:%S}" if r.predicted_finish_p95 else "p95 never"
                how = f" by {r.action}" + (f" to {r.lent_to}" if r.lent_to else "") if r.action else ""
                print(f"  DeviationReport {r.commitment_id} [{cause}] {r.outcome}{how}: {done}, latest_finish "
                      f"{r.latest_finish:%H:%M}; now {seg.start:%H:%M:%S}–{seg.end:%H:%M:%S} @ {seg.gbps:g} Gbps "
                      f"on {r.commitment.circuit_id} (vlan {r.commitment.binding.vlan})")
        for result in out.get("repair_results", []):
            for why in result.tried:
                print(f"    {result.commitment.commitment_id} tried {why}")
        return out

    def print_commitments(self):
        print("  Commitments:")
        for c in self.ctx.committed():
            seg, req = c.commitment.rate_profile[0], c.reserved_offer.request
            print(f"    {c.commitment.commitment_id} {req.id} ({req.workflow_id}, priority {req.priority}): "
                  f"{req.bytes / 1e12:g} TB by {req.window.latest_finish:%H:%M}; {seg.start:%H:%M:%S}–{seg.end:%H:%M:%S}"
                  f" @ {seg.gbps:g} Gbps on {c.commitment.circuit_id}"
                  f"   [{hops(self.ctx.topology, c.reserved_offer.placement.path)}]")

    def finishes(self, *instance_ids):
        """When the simulated transfers actually finish (None: not by the end of the day)."""
        out = {i: self.net.flow_trace(i, t(23)).finished_at for i in instance_ids}
        print("  simulated: " + ", ".join(f"{i} finishes {f:%H:%M:%S}" if f else f"{i} does not finish"
                                         for i, f in out.items()))
        return out


# ── runtime demo for presentations (step 7e): one line per stage of graph B ──

def slot_ranges(ledger, slots):
    """{(link, slot)} → {link: ['10:15–12:00', ...]} with adjacent slots merged."""
    by_link = {}
    for link, i in sorted(slots):
        by_link.setdefault(link, []).append(i)
    out = {}
    for link, idx in by_link.items():
        ranges, first, last = [], idx[0], idx[0]
        for i in idx[1:]:
            if i == last + 1:
                last = i
                continue
            ranges.append((first, last))
            first = last = i
        ranges.append((first, last))
        out[link] = [f"{ledger.slot_start(a):%H:%M}–{ledger.slot_start(b + 1):%H:%M}" for a, b in ranges]
    return out


def short_name(link):
    """'L2:esnet-atl>esnet-chi' → 'L2'"""
    return link.split(":")[0]


class PipelineSession:
    """Prints each run of graph B as the stages of the runtime: forecast → detection → assessment → repair → report."""

    def __init__(self, title, story, net, ctx):
        self.net, self.ctx, self.graph = net, ctx, build_runtime_graph()
        print(f"\n{'=' * 100}\n{title}\n{'=' * 100}\n{story}")
        self.print_commitments()

    def print_commitments(self):
        print("\n  Commitments held by the network agent:")
        for c in self.ctx.committed():
            seg, req = c.commitment.rate_profile[0], c.reserved_offer.request
            print(f"    {c.commitment.commitment_id}  {req.id} ({req.workflow_id}, priority {req.priority}): "
                  f"{req.bytes / 1e12:g} TB, deadline {req.window.latest_finish:%H:%M} | reserved "
                  f"{seg.start:%H:%M}–{seg.end:%H:%M} @ {seg.gbps:g} Gbps on {c.commitment.circuit_id}  "
                  f"[{hops(self.ctx.topology, c.reserved_offer.placement.path)}]")

    def happens(self, text):
        print(f"\n  ~ in the network: {text}")

    def print_forecast(self, link, start, end, now, title=None):
        """The ledger's view of one link: measured now, forecast ahead (typical / pessimistic)."""
        ledger = self.ctx.ledger
        print(f"    {title or 'ledger'} for {short_name(link)} at {now:%H:%M} "
              "(capacity left by non-SciNet traffic, Gbps; typical p50 / pessimistic p95):")
        rows = []
        for i in ledger.slots_covering(start, end):
            o = ledger.observed(link, i)
            kind = "forecast" if o.source == "forecast" else "measured"
            down_p50 = o.p50_gbps == 0 if o.p50_gbps is not None else not o.up
            row = (kind, round(o.capacity("p50"), 1), round(o.capacity("p95"), 1), down_p50, not o.up)
            a, b = ledger.slot_start(i), ledger.slot_start(i + 1)
            if rows and rows[-1][2:] == row:
                rows[-1] = (rows[-1][0], b, *row)
            else:
                rows.append((a, b, *row))
        for a, b, kind, p50, p95, down_p50, down_p95 in rows:
            state = ("DOWN" if down_p50 and down_p95 else
                     f"{p50:>5g} / {p95:<5g}" + ("  (down in the bad case)" if down_p95 else ""))
            print(f"      {a:%H:%M}–{b:%H:%M}  {kind:<8}  {state}")

    def run(self, event, now, label):
        print(f"\n  {now:%H:%M}  EVENT  {label}")
        out = self.graph.invoke({"event": event, "now": now}, context=self.ctx)
        ledger = self.ctx.ledger
        short = slot_ranges(ledger, out.get("short_slots", set()))
        if short:
            text = "; ".join(f"{short_name(link)} {', '.join(r)}" for link, r in short.items())
            print(f"    [forecast]   our booked slots that became short: {text}")
        else:
            print("    [forecast]   no booked slot became short")
        deviations = out.get("deviations", [])
        if not deviations:
            print(f"    [detection]  checked {', '.join(out.get('checked', [])) or 'nothing'}: no deviation")
        for d in deviations:
            branch = ("flow / slow (throughput below the reserved rate)" if d.slow else
                      "flow / overrun (cannot carry the rest in time)" if d.overrun else "link (damage ahead)")
            where = f" at {', '.join(short_name(l) for l in d.links)}" if d.links else ""
            print(f"    [detection]  {d.commitment_id}: {branch} → cause {d.cause}{where}")
        for a in out.get("assessments", []):
            finish = (f"through by p50 {a.finish[0]:%H:%M} / p95 {a.finish[1]:%H:%M}" if a.finish
                      else "not through before its reservation ends")
            verdict = "fine, no repair" if a.finishes_in_reservation else "needs a repair"
            print(f"    [assess]     {a.commitment_id}: {a.remaining_bytes / 1e12:g} TB left, {finish} → {verdict}")
        for cid in out.get("retry_deferred", []):
            print(f"    [triage]     {cid}: same conditions as the failed attempt; retry later, no new report")
        for p in out.get("plans", []):
            print(f"    [plan]       {p.assessment.commitment_id}: try {' → '.join(p.steps)}")
        for result in out.get("repair_results", []):
            for why in result.tried:
                print(f"    [repair]     {result.commitment.commitment_id}: {why}")
        for rs in out.get("reports", {}).values():
            for r in rs:
                seg = r.commitment.rate_profile[0]
                how = f"repaired by {r.action}" + (f" (lends to {r.lent_to})" if r.lent_to else "") if r.action else "UNRESOLVED"
                p95 = f"p95 {r.predicted_finish_p95:%H:%M}" if r.predicted_finish_p95 else "p95 never"
                print(f"    [report]     → scheduling agent: {r.commitment_id} [{r.cause}] {how}; {p95}, deadline "
                      f"{r.latest_finish:%H:%M}; now {seg.start:%H:%M}–{seg.end:%H:%M} @ {seg.gbps:g} Gbps on "
                      f"{r.commitment.circuit_id}")
        return out

    def finishes(self, *instance_ids):
        out = {i: self.net.flow_trace(i, t(23)).finished_at for i in instance_ids}
        print("\n  Outcome (simulated): " + ", ".join(f"{i} finishes {f:%H:%M}" if f else f"{i} does not finish"
                                                    for i, f in out.items()))
        return out
