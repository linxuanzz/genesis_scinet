"""Step 5a demo: the scheduling agent's whole conversation with graph A (quote → pick offers → reserve →
commit), sent through the single entry point ``build_protocol_graph()``. After every message it prints
what the network agent now holds: the ledger on the main path, its bookings, and the SENSE instances.

How to run (from the repository root), with one scenario as the argument:
    python -m <package path>.tests.test_step5a_demo test1     (e.g. network_agent.tests...)
scenarios: test1 / test2 / test3 / test4
"""

from datetime import timedelta

from ..graphs.protocol import build_protocol_graph
from ..schemas import (
    CommitAck, CommitRequest, ErrorResponse, QuoteRequest, QuoteResponse, ReserveAck, ReserveRequest,
)
from .helpers import L2, MAIN, make_ctx, make_net, t, tr
from .printing import hops, print_network

LEDGER_SPAN = (t(9), t(15))                       # time range of the printed ledger


def sec(s):
    return timedelta(seconds=s)


class Session:
    """One network agent (graph A + its context) and a printer for everything sent to it."""

    def __init__(self, title, net):
        self.net, self.ctx, self.graph = net, make_ctx(net), build_protocol_graph()
        print_network(title, net)
        self.print_state(t(9))

    def send(self, verb, msg, now):
        print(f"\n{'─' * 100}\n{now:%H:%M:%S}  scheduling agent → network agent: {verb}")
        print_request(msg)
        resp = self.graph.invoke({"verb": verb, "raw": msg.model_dump(), "now": now}, context=self.ctx)["response"]
        print("network agent → scheduling agent:")
        print_response(resp, self.ctx)
        self.print_state(now)
        return resp

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
            print(f"    {r.reserve_id} ({r.state}, expires {r.expires_at:%H:%M:%S})  {i.offer_id}: "
                  f"{p.start:%H:%M:%S}–{p.end:%H:%M:%S} @ {p.gbps:g} Gbps   "
                  f"booking {i.booking_id} = {ctx.ledger.booking(i.booking_id).state}")
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
    if isinstance(msg, QuoteRequest):
        print(f"  quote_id {msg.quote_id}, mode {msg.mode}")
        for x in msg.bundle:
            print(f"  {x.id} ({x.workflow_id}): {x.src} → {x.dst}, {x.bytes / 1e12:g} TB, "
                  f"window {x.window.earliest_start:%H:%M}–{x.window.latest_finish:%H:%M}")
    elif isinstance(msg, ReserveRequest):
        print(f"  request_id {msg.request_id}, quote_id {msg.quote_id}, offers {msg.offer_ids}")
    elif isinstance(msg, CommitRequest):
        print(f"  request_id {msg.request_id}, reserve_id {msg.reserve_id}")


def print_response(resp, ctx):
    if isinstance(resp, ErrorResponse):
        print(f"  ERROR {resp.code}: {resp.detail}")
    elif isinstance(resp, QuoteResponse):
        for r in resp.results:
            if r.status != "feasible":
                print(f"  {r.transfer_id}: {r.status} ({r.reason.cause}: {r.reason.detail})")
            for o in r.offers:
                s, p = o.rate_profile[0], ctx.offer_book[o.offer_id].placement   # path is not sent; shown from offer_book
                print(f"  {o.offer_id}: {s.start:%H:%M} @ {s.gbps:>5g} Gbps → {o.predicted_finish_p50:%H:%M:%S}"
                      f"   blocked_by={o.blocked_by}   [{hops(ctx.topology, p.path)}]")
    elif isinstance(resp, ReserveAck):
        print(f"  ReserveAck {resp.reserve_id}: offers {resp.offer_ids}, expires {resp.expires_at:%H:%M:%S}")
    elif isinstance(resp, CommitAck):
        print(f"  CommitAck {resp.reserve_id}:")
        for c in resp.commitments:
            seg, b = c.rate_profile[0], c.binding
            print(f"    {c.commitment_id}: {c.transfer_id} ({c.workflow_id}) on circuit {c.circuit_id}, "
                  f"{seg.start:%H:%M:%S}–{seg.end:%H:%M:%S} @ {seg.gbps:g} Gbps")
            print(f"      binding: {b.src_uri} → {b.dst_uri}, vlan {b.vlan}, interface {b.interface}")


def quote_t1_t2(quote_id="q1"):
    return QuoteRequest(quote_id=quote_id, bundle=[tr("T1"), tr("T2", nbytes=10**12)], mode="all_or_nothing")


# ── scenarios ─────────────────────────────────────────────────────────────

def happy_path(title):
    """T1 takes the 12:00 @ 100 Gbps offer, T2 the 09:00 @ 40 Gbps one; both reserved together, then committed."""
    s = Session(title, make_net())
    s.send("quote", quote_t1_t2(), t(9))
    s.send("reserve", ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T1/2", "q1/T2/1"]), t(9) + sec(20))
    return s.send("commit", CommitRequest(request_id="c1", reserve_id="rsv-1"), t(9) + sec(40))


def recheck_conflict(title):
    """Others take 30 more Gbps on L2 after the quote. Reserving at 09:10, the quote-time samples are stale,
    so recheck refreshes them and the debit is refused before SENSE is called; the scheduling agent re-quotes."""
    s = Session(title, make_net())
    s.send("quote", quote_t1_t2(), t(9))
    s.net.add_background(L2, t(9), t(12), 30)
    s.event("network change: background traffic on L2 grows by 30 Gbps over 09:00–12:00 (only 10 Gbps left)")
    s.send("reserve", ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T1/1"]), t(9, 10))
    s.send("quote", quote_t1_t2("q2"), t(9, 10))
    s.send("reserve", ReserveRequest(request_id="r2", quote_id="q2", offer_ids=["q2/T1/1"]), t(9, 10) + sec(20))
    return s.send("commit", CommitRequest(request_id="c2", reserve_id="rsv-2"), t(9, 10) + sec(40))


def sense_refuses(title):
    """Others take 30 Gbps on L2 over 12:00–13:00 right after the quote. At 09:01 the samples are still fresh,
    so the ledger does not know; SENSE accepts q1/T2/1 and refuses q1/T1/2, and the whole group is undone."""
    s = Session(title, make_net())
    s.send("quote", quote_t1_t2(), t(9))
    s.net.add_background(L2, t(12), t(13), 30)
    s.event("network change: background traffic on L2 takes 30 Gbps over 12:00–13:00 (telemetry has not reported it yet)")
    return s.send("reserve", ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T2/1", "q1/T1/2"]), t(9, 1))


def commit_retry(title):
    """SENSE fails the first commit; nothing is rolled back, and the retry within the TTL succeeds."""
    s = Session(title, make_net())
    s.send("quote", quote_t1_t2(), t(9))
    s.send("reserve", ReserveRequest(request_id="r1", quote_id="q1", offer_ids=["q1/T1/2"]), t(9) + sec(10))
    s.ctx.sense.fail_next("commit")
    s.event("SENSE will fail the next commit call (injected)")
    s.send("commit", CommitRequest(request_id="c1", reserve_id="rsv-1"), t(9) + sec(20))
    return s.send("commit", CommitRequest(request_id="c2", reserve_id="rsv-1"), t(9) + sec(30))


SCENARIOS = {
    "test1": ("Happy path: quote T1 + T2, reserve one offer each, commit", happy_path, CommitAck),
    "test2": ("Capacity lost after the quote: recheck refuses the reserve, re-quote and reserve again", recheck_conflict, CommitAck),
    "test3": ("SENSE refuses one offer of the group: the other is cancelled and the ledger rolled back", sense_refuses, ErrorResponse),
    "test4": ("SENSE commit fails once: reservation kept, retry succeeds", commit_retry, CommitAck),
}


def test_demo_printout():
    for title, run, expected in SCENARIOS.values():
        assert isinstance(run(title), expected)


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2 or sys.argv[1] not in SCENARIOS:
        print(f"Usage: python -m {__spec__.name} <scenario>")
        for name, (title, _, _) in SCENARIOS.items():
            print(f"  {name}   {title}")
        sys.exit(1)
    title, run, _ = SCENARIOS[sys.argv[1]]
    run(title)
