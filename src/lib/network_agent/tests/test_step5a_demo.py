"""Step 5a demo: the scheduling agent's whole conversation with graph A (quote → pick offers → reserve →
commit), sent through the single entry point ``build_protocol_graph()``. After every message it prints
what the network agent now holds: the ledger on the main path, its bookings, and the SENSE instances.

How to run (from the repository root), with one scenario as the argument:
    python -m <package path>.tests.test_step5a_demo test1     (e.g. network_agent.tests...)
scenarios: test1 / test2 / test3 / test4
"""

from ..schemas import CommitAck, CommitRequest, ErrorResponse, ReserveRequest
from .helpers import L2, make_net, quote_t1_t2, t
from .printing import Session, sec


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
