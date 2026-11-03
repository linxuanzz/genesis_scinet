"""Step 5b final demo: every verb once, on its normal path, sent through graph A's single entry point.
After every message it prints the ledger on the main path, the reservations and the SENSE instances.

    query → reserve → commit → modify → release (one offer) → release (the rest)

How to run (from the repository root):
    python -m <package path>.tests.test_step5b_final_demo     (e.g. network_agent.tests...)
"""

from ..schemas import CommitAck, ModifyAck, QueryResponse, ReleaseAck, ReleaseRequest, ReserveAck
from .helpers import C1, R1, make_net, modify_t1, query_t1_t2, t
from .printing import Session, sec

TITLE = "Every verb on its normal path: query, reserve, commit, modify, release"


def walkthrough():
    """T1 takes the 12:00 @ 100 Gbps offer, T2 the 09:00 @ 40 Gbps one; both are reserved and committed.
    T1 is then slowed to 50 Gbps until 14:00, T2 finishes before its predicted 09:03:20 and gives back its
    circuit, and finally the workflow is cancelled, so T1's circuit is released too."""
    s = Session(TITLE, make_net())
    replies = [s.send("query", query_t1_t2(), t(9)),
               s.send("reserve", R1, t(9) + sec(10)),
               s.send("commit", C1, t(9) + sec(20))]
    s.event("the scheduling agent wants T1 to leave half of the path free after 12:00")
    replies.append(s.send("modify", modify_t1("m1", t(14), 50), t(9, 1)))
    s.event("T2 finished at 09:02, before its predicted 09:03:20")
    replies.append(s.send("release", ReleaseRequest(request_id="x1", reserve_id="rsv-1", offer_ids=["q1/T2/1"]),
                          t(9, 2)))
    s.event("WF-1 is cancelled; T1 is no longer needed")
    replies.append(s.send("release", ReleaseRequest(request_id="x2", reserve_id="rsv-1"), t(9, 3)))
    return s, replies


def test_final_demo_printout():
    s, replies = walkthrough()
    assert [type(r) for r in replies] == [QueryResponse, ReserveAck, CommitAck, ModifyAck, ReleaseAck, ReleaseAck]
    assert s.ctx.reservations["rsv-1"].state == "released" and not s.ctx.commitments
    assert all(st.state == "cancelled" for st in s.ctx.sense._states.values())


if __name__ == "__main__":
    walkthrough()
