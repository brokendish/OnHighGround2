"""
Reroute-threshold parameter sweep.

Seven fixed traces × 9 reroute_threshold values × 5 noise levels × 10 trials
= 3 150 engine runs.  Results are stored in `reroute_results` and written to
reports/parameter_sweep/reroute.md by the sessionfinish hook.

Scenarios
---------
T1  on-route walking           — false-positive detection
T2  deviate 20 m, return       — mild deviation
T3  deviate 40 m, return       — moderate deviation
T4  deviate 75 m, no return    — strong deviation
T5  deviate 150 m, no return   — severe deviation
T6  jitter on route σ=10 m     — GPS noise only, no real deviation
T7  GPS loss then +50 m off    — GPS recovery scenario
"""

import pytest

from engine import NavigationEngine, replay_trace
from fixtures.trace_generators import (
    straight_approach,
    deviate_from_route,
    add_gaussian_noise,
    add_gps_loss,
)
from sweep_config import (
    REROUTE_THRESHOLD_SWEEP,
    NOISE_SIGMA_SWEEP,
    NOISE_TRIALS,
    NOISE_SEED_BASE,
    WALKING_SPEED,
    GPS_STEP_SEC,
    CURRENT_CONSECUTIVE,
    CURRENT_DEBOUNCE_SEC,
    CURRENT_ARRIVAL_RADIUS,
)

# ── Shared geometry ──────────────────────────────────────────────────────────

DEST  = (35.6800, 139.6600)
START = (DEST[0] + 400 / 111_111, DEST[1])    # 400 m north — long enough to deviate

ROUTE = [
    {'lat': START[0],               'lng': START[1]},
    {'lat': START[0] - 200/111_111, 'lng': START[1]},
    {'lat': DEST[0],                'lng': DEST[1]},
]

# ── Scenarios ────────────────────────────────────────────────────────────────

def _on_route():
    return straight_approach(START, DEST, WALKING_SPEED, GPS_STEP_SEC)

def _dev(dev_m, ret):
    return deviate_from_route(ROUTE, deviation_m=dev_m, return_to_route=ret,
                              speed=WALKING_SPEED, step_sec=GPS_STEP_SEC)

def _t6_jitter():
    base = straight_approach(START, DEST, WALKING_SPEED, GPS_STEP_SEC)
    return add_gaussian_noise(base, sigma_m=10, accuracy_field=True, seed=NOISE_SEED_BASE)

def _t7_gps_loss():
    base  = straight_approach(START, DEST, WALKING_SPEED, GPS_STEP_SEC)
    # Duration of on-route walk before loss (seconds) ≈ 40 % of total trace
    total_sec  = base[-1]['timestamp']
    loss_start = total_sec * 0.35
    loss_dur   = 30.0                        # 30-second tunnel
    after_loss = add_gps_loss(base, loss_start, loss_dur)

    # Offset all post-loss fixes 50 m east (simulates GPS recovery off-route)
    result = []
    boundary = loss_start + loss_dur
    for fix in after_loss:
        if fix['timestamp'] > boundary:
            import math
            dlon = 50 / (111_111 * math.cos(math.radians(fix['lat'])))
            result.append({**fix, 'lon': fix['lon'] + dlon})
        else:
            result.append(fix)
    return result

SCENARIOS = {
    'T1_on_route':      _on_route,
    'T2_dev_20m_ret':   lambda: _dev(20,  True),
    'T3_dev_40m_ret':   lambda: _dev(40,  True),
    'T4_dev_75m_no_ret':lambda: _dev(75,  False),
    'T5_dev_150m_no_ret':lambda: _dev(150, False),
    'T6_jitter':        _t6_jitter,
    'T7_gps_loss_50m':  _t7_gps_loss,
}

# ── Sweep ────────────────────────────────────────────────────────────────────

def test_reroute_sweep(reroute_results):
    """
    Run full reroute_threshold × noise sweep over all 7 scenarios.
    Collects results into reroute_results for report generation.
    """
    for scenario_name, trace_factory in SCENARIOS.items():
        for threshold in REROUTE_THRESHOLD_SWEEP:
            for sigma in NOISE_SIGMA_SWEEP:
                fired_count  = 0
                delays_sec   = []

                for trial in range(NOISE_TRIALS):
                    base_trace = trace_factory()

                    # T6 jitter has its own noise; add extra noise on top only if sigma > 0
                    if sigma > 0 and scenario_name != 'T6_jitter':
                        trace = add_gaussian_noise(
                            base_trace, sigma_m=sigma,
                            seed=NOISE_SEED_BASE + trial,
                        )
                    else:
                        trace = base_trace

                    eng = NavigationEngine(
                        arrival_radius=CURRENT_ARRIVAL_RADIUS,
                        reroute_threshold=threshold,
                    )
                    eng.set_destination(*DEST)
                    eng.set_route(ROUTE)

                    events  = replay_trace(eng, trace)
                    reroutes = [e for e in events if e.event_type == 'reroute_triggered']

                    if reroutes:
                        fired_count += 1
                        delays_sec.append(reroutes[0].data['debounce_delay_sec'])

                reroute_results.append({
                    'scenario':         scenario_name,
                    'reroute_threshold':threshold,
                    'noise_sigma':      sigma,
                    'fired_rate':       fired_count / NOISE_TRIALS,
                    'mean_delay_sec':   (
                        sum(delays_sec) / len(delays_sec) if delays_sec else None
                    ),
                    # Expected effective delay formula (informational)
                    'expected_min_delay_sec': (
                        CURRENT_CONSECUTIVE * GPS_STEP_SEC + CURRENT_DEBOUNCE_SEC
                    ),
                })

    # ── Sanity assertions ─────────────────────────────────────────────────
    def _get(scenario, threshold, sigma=0):
        return next(
            r for r in reroute_results
            if r['scenario'] == scenario
            and r['reroute_threshold'] == threshold
            and r['noise_sigma'] == sigma
        )

    # T1 on-route sigma=0 must have 0 % false positives at all thresholds
    for th in REROUTE_THRESHOLD_SWEEP:
        res = _get('T1_on_route', th, sigma=0)
        assert res['fired_rate'] == 0.0, (
            f"T1 sigma=0 threshold={th}m: expected 0% reroute, got {res['fired_rate']:.0%}"
        )

    # T5 150m deviation sigma=0 must fire at all tested thresholds (≤ 100m)
    for th in REROUTE_THRESHOLD_SWEEP:
        res = _get('T5_dev_150m_no_ret', th, sigma=0)
        assert res['fired_rate'] == 1.0, (
            f"T5 sigma=0 threshold={th}m: expected 100% reroute, got {res['fired_rate']:.0%}"
        )
