"""Step 5b demo: what happens after a reserve, sent through graph A's single entry point. Release and
modify, expiry, and resent requests. After every message it prints the ledger on the main path, the
reservations and the SENSE instances, plus what the sweep reclaimed and whether the reply was replayed.

How to run (from the repository root), with one scenario as the argument:
    python -m <package path>.tests.test_step5b_demo test1     (e.g. network_agent.tests...)
scenarios: test1 / test2 / test3 / test4 / test5
"""

from ..schemas import ErrorResponse, ModifyAck, ReleaseAck, ReleaseRequest, ReserveAck, ReserveRequest
from .helpers import C1, L2, R1, make_net, modify_t1, query_t1_t2, t
from .printing import Session, sec


# ── scenarios ─────────────────────────────────────────────────────────────

def change_plans(title):
    """Both committed; T2 finishes early and gives back its slot, T1 is slowed to 50 Gbps until 14:00,
    and finally the rest is released."""
    s = Session(title, make_net())
    s.send("query", query_t1_t2(), t(9))
    s.send("reserve", R1, t(9) + sec(10))
    s.send("commit", C1, t(9) + sec(20))
    s.event("T2 finished early")
    s.send("release", ReleaseRequest(request_id="x1", reserve_id="rsv-1", offer_ids=["q1/T2/1"]), t(9, 4))
    s.send("modify", modify_t1("m1", t(14), 50), t(9, 5))
    return s.send("release", ReleaseRequest(request_id="x2", reserve_id="rsv-1"), t(9, 6))


def reservation_expires(title):
    """Reserved but never committed: the next message, a new query, first reclaims rsv-1, so its offers see
    the capacity again; the late commit is told the reservation expired."""
    s = Session(title, make_net())
    s.send("query", query_t1_t2(), t(9))
    s.send("reserve", R1, t(9) + sec(10))
    s.event("the scheduling agent goes quiet past the reservation's 60 s TTL")
    s.send("query", query_t1_t2("q2"), t(9, 1) + sec(30))
    return s.send("commit", C1, t(9, 1) + sec(40))


def lost_replies(title):
    """Replies get lost and the scheduling agent resends. A resent reserve and commit are answered from the
    cache; a failed commit is not cached, so resending it really retries; reusing r1 for other offers is refused."""
    s = Session(title, make_net())
    s.send("query", query_t1_t2(), t(9))
    s.send("reserve", R1, t(9) + sec(10))
    s.event("the ReserveAck was lost; the scheduling agent resends r1")
    s.send("reserve", R1, t(9) + sec(15))
    s.ctx.sense.fail_next("commit")
    s.event("SENSE will fail the next commit call (injected)")
    s.send("commit", C1, t(9) + sec(20))
    s.send("commit", C1, t(9) + sec(25))
    s.event("the CommitAck was lost; the scheduling agent resends c1")
    s.send("commit", C1, t(9) + sec(30))
    s.event("a bug in the scheduling agent reuses r1 for other offers")
    return s.send("reserve", ReserveRequest(request_id="r1", query_id="q1", offer_ids=["q1/T1/1"]), t(9) + sec(35))


def query_expires(title):
    """The query is valid for 15 minutes; a reserve at 09:16 is refused as expired, and a fresh query works."""
    s = Session(title, make_net())
    s.send("query", query_t1_t2(), t(9))
    s.send("reserve", R1, t(9, 16))
    s.send("query", query_t1_t2("q2"), t(9, 16))
    return s.send("reserve", ReserveRequest(request_id="r2", query_id="q2", offer_ids=["q2/T1/2", "q2/T2/1"]),
                  t(9, 16) + sec(10))


def modify_refused(title):
    """Others take 30 Gbps on L2 over 13:00–14:00 after the commit; telemetry has not reported it yet, so
    the ledger accepts stretching T1 to 14:00 @ 100 Gbps but SENSE refuses, and the old profile is put back.
    Asking for 70 Gbps instead fits."""
    s = Session(title, make_net())
    s.send("query", query_t1_t2(), t(9))
    s.send("reserve", R1, t(9) + sec(10))
    s.send("commit", C1, t(9) + sec(20))
    s.net.add_background(L2, t(13), t(14), 30)
    s.event("network change: background traffic on L2 takes 30 Gbps over 13:00–14:00 (telemetry has not reported it yet)")
    s.send("modify", modify_t1("m1", t(14), 100), t(9, 1))
    return s.send("modify", modify_t1("m2", t(14), 70), t(9, 2))


SCENARIOS = {
    "test1": ("Change of plans: partial release, modify, release the rest", change_plans, ReleaseAck),
    "test2": ("Reservation expires: reclaimed by the next message, late commit refused", reservation_expires, ErrorResponse),
    "test3": ("Lost replies: resends answered from the cache, a failed commit retried", lost_replies, ErrorResponse),
    "test4": ("Query expires: reserve after 15 minutes refused, re-query", query_expires, ReserveAck),
    "test5": ("SENSE refuses a modify: ledger put back; a smaller change fits", modify_refused, ModifyAck),
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
