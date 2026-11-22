"""Step 7 network forecast: the ledger's future slots (runtime/forecast.py).

    observed = nominal − registered non-SciNet reservations − predicted unregistered traffic (p50 / p95)
    predicted unregistered traffic = w × start + (1 − w) × baseline, w = exp(−lead time / decay)

CFG: forecast_decay_seconds 1800, outage_repair_p50 / p95 1 h / 3 h, forecast values valid 5 minutes.
"""

import math

import pytest

from ..src.adapters.forecast_inputs import MockForecastInputs
from ..src.graphs.protocol.query import build_query_graph
from ..src.models.schemas import TelemetryAlert, Tick
from ..src.runtime.forecast import FORECAST, forecast_links, refresh, update_forecast
from ..src.state.ledger import Observation
from .helpers import L2, L3, MAIN, make_committed_ctx, make_ctx, make_net, query_t1_t2, runtime, t

TB = 10**12
DECAY = 1800


def slot(ctx, at):
    return ctx.ledger.slots_covering(at, at.replace(second=1))[0]


def observed(ctx, link, at):
    return ctx.ledger.observed(link, slot(ctx, at))


def link_alert(kind, link_id, at):
    return TelemetryAlert(alert_id=f"{kind}-{at:%H%M}", kind=kind, link_id=link_id, start=at, observed_at=at,
                          source="mock")


# ── who writes which slot ─────────────────────────────────────────────────

def test_current_slot_is_measured_future_slots_are_forecast():
    """Registered reservations are known ahead: the forecast has L2 at 40 until 12:00, 100 after."""
    ctx = make_ctx(make_net())
    refresh(ctx, [(MAIN, t(9), t(15))], t(9))
    assert observed(ctx, L2, t(9)).source == "mock"                  # telemetry
    later = [observed(ctx, L2, at) for at in (t(11, 45), t(12))]
    assert [(o.source, o.gbps, o.p50_gbps, o.up) for o in later] == [(FORECAST, 40, 40, True), (FORECAST, 100, 100, True)]


def test_unregistered_traffic_fades_from_the_measurement_to_the_baseline():
    net = make_net()
    net.add_background(L3, t(9), t(15), 50, registered=False)        # telemetry sees it; nothing announced it
    ctx = make_ctx(net)
    forecast_links(ctx, [L3], t(10))
    assert observed(ctx, L3, t(10)).gbps == 50                       # measured now
    weight = math.exp(-900 / DECAY)                                  # 10:15 is 15 minutes ahead
    assert observed(ctx, L3, t(10, 15)).gbps == pytest.approx(100 - 50 * weight)
    assert observed(ctx, L3, t(14)).gbps == pytest.approx(100, abs=0.1)   # far ahead: the (zero) baseline


def test_the_baseline_spread_widens_with_lead_time():
    net = make_net()
    ctx = make_ctx(net)
    ctx.forecast_inputs = MockForecastInputs(net, baseline_gbps={L3: (10, 30)})
    forecast_links(ctx, [L3], t(10))
    near, far = observed(ctx, L3, t(10, 15)), observed(ctx, L3, t(20))
    assert near.p50_gbps - near.gbps < far.p50_gbps - far.gbps
    assert (far.p50_gbps, far.gbps) == (pytest.approx(90), pytest.approx(70))


def test_values_are_clamped():
    net = make_net()                                                 # 60 registered on L2 until 12:00
    ctx = make_ctx(net)
    ctx.forecast_inputs = MockForecastInputs(net, baseline_gbps={L2: (20, 60)})
    forecast_links(ctx, [L2], t(9))
    assert observed(ctx, L2, t(11)).gbps == 0                        # 100 − 60 − ~60, not negative


def test_planning_books_against_the_pessimistic_value():
    """A p95 baseline of 30 Gbps on L2 leaves 70: graph A offers 70 at 12:00 instead of 100."""
    net = make_net()
    ctx = make_ctx(net)
    ctx.forecast_inputs = MockForecastInputs(net, baseline_gbps={L2: (0, 30)})
    out = build_query_graph().invoke({"raw": query_t1_t2().model_dump(), "now": t(9)}, context=ctx)
    t1 = next(r for r in out["response"].results if r.transfer_id == "T1")
    noon = [o.rate_profile[0].gbps for o in t1.offers if o.rate_profile[0].start == t(12)]
    assert max(noon) == 70                                           # not 100


# ── outages ───────────────────────────────────────────────────────────────

def test_planned_outage_is_down_in_both_cases():
    net = make_net()
    net.add_outage("L3", t(11), t(11, 30))
    ctx = make_ctx(net)
    forecast_links(ctx, [L3], t(9))
    down = observed(ctx, L3, t(11, 15))
    assert (down.up, down.gbps, down.p50_gbps) == (False, 0, 0)
    assert observed(ctx, L3, t(11, 30)).up


def test_unplanned_outage_lasts_for_the_typical_and_the_bad_case():
    """A link_down alert at 10:00: down in both cases until 11:00, in the bad case only until 13:00."""
    net = make_net()
    net.add_outage("L3", t(10), t(23), planned=False)
    ctx = make_ctx(net)
    update_forecast(ctx, link_alert("link_down", "L3", t(10)), t(10))
    assert ctx.unplanned_outages[L3] == t(10)
    states = {at: (observed(ctx, L3, at).up, observed(ctx, L3, at).p50_gbps)
              for at in (t(10, 45), t(11), t(12, 45), t(13))}
    assert states == {t(10, 45): (False, 0), t(11): (False, 100), t(12, 45): (False, 100), t(13): (True, 100)}


def test_link_up_ends_an_unplanned_outage():
    net = make_net()
    net.add_outage("L3", t(10), t(10, 20), planned=False)
    ctx = make_ctx(net)
    update_forecast(ctx, link_alert("link_down", "L3", t(10)), t(10))
    update_forecast(ctx, link_alert("link_up", "L3", t(10, 20)), t(10, 20))
    assert L3 not in ctx.unplanned_outages and observed(ctx, L3, t(10, 45)).up


def test_a_link_found_down_without_an_alert_counts_as_unplanned():
    net = make_net()
    net.add_outage("L3", t(9, 50), t(23), planned=False)
    ctx = make_ctx(net)
    update_forecast(ctx, Tick(), t(10))
    assert ctx.unplanned_outages[L3] == t(10) and not observed(ctx, L3, t(10, 15)).up


# ── what the forecast tells detection ─────────────────────────────────────

def test_a_change_now_is_handled_ahead_for_a_transfer_not_started_yet():
    """cmt-1 = T1 at 12:00 @ 100 on MAIN, not started. At 10:00 unregistered traffic takes 70 of L2: the
    forecast for 12:00 (two hours ahead) still keeps a little of it, so 12:00 is short at 10:00, and the
    link branch handles cmt-1 now rather than when its transfer starts."""
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/2")
    net.add_background(L2, t(10), t(15), 70, registered=False)
    alert = TelemetryAlert(alert_id="c1", kind="link_capacity_below", link_id=L2, start=t(10), measured_gbps=0,
                           observed_at=t(10), source="mock")
    out = runtime(ctx, alert, t(10))
    assert (L2, slot(ctx, t(12))) in out["short_slots"]
    [d] = out["deviations"]
    assert (d.commitment_id, d.cause, d.damage[0].start) == ("cmt-1", "congestion", t(12))


def test_a_fast_decay_forgets_the_change_by_then():
    """The same with a decay of one minute: at 12:00 the forecast is back at the baseline, nothing is short."""
    net = make_net()
    ctx = make_committed_ctx(net, "q1/T1/2")
    ctx.cfg = ctx.cfg.model_copy(update={"forecast_decay_seconds": 60})
    net.add_background(L2, t(10), t(15), 70, registered=False)
    alert = TelemetryAlert(alert_id="c1", kind="link_capacity_below", link_id=L2, start=t(10), measured_gbps=0,
                           observed_at=t(10), source="mock")
    out = runtime(ctx, alert, t(10))
    assert out["short_slots"] == set() and out["deviations"] == []


def test_a_tick_recomputes_only_expired_forecasts():
    ctx = make_ctx(make_net())
    assert update_forecast(ctx, Tick(), t(9)).refreshed
    assert update_forecast(ctx, Tick(), t(9, 4)).refreshed == []      # valid until 09:05
    assert update_forecast(ctx, Tick(), t(9, 5)).refreshed


def test_p50_reads_the_typical_value():
    o = Observation(gbps=20, source=FORECAST, at=t(9), valid_until=t(9, 5), up=False, p50_gbps=80)
    assert (o.capacity("p50"), o.capacity("p95")) == (80, 0)
