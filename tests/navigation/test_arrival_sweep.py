"""
Arrival-radius parameter sweep.

Five fixed traces × 10 arrival_radius values × 5 noise levels × 10 trials
= 2 500 engine runs.  Results are stored in the session-scoped `arrival_results`
fixture (defined in conftest.py) and converted to reports/parameter_sweep/arrival.md
by the pytest_sessionfinish hook.

Scenarios
---------
T1  straight approach — arrives exactly at destination
T2  overshoot 10 m    — passes destination by 10 m
T3  overshoot 30 m    — today's field test phenomenon (passes by 30 m)
T4  stop 5 m short    — stops just before destination
T5  circle 30 m       — circles destination at 30 m radius
"""

import math

import pytest

from engine import NavigationEngine, replay_trace
from fixtures.trace_generators import (
    straight_approach,
    overshoot,
    circle_around,
    add_gaussian_noise,
)
from sweep_config import (
    ARRIVAL_RADIUS_SWEEP,
    NOISE_SIGMA_SWEEP,
    NOISE_TRIALS,
    NOISE_SEED_BASE,
    WALKING_SPEED,
    GPS_STEP_SEC,
)

# ── Shared geometry ──────────────────────────────────────────────────────────

DEST  = (35.6800, 139.6600)                            # synthetic destination
START = (DEST[0] + 200 / 111_111, DEST[1])             # 200 m north

# 3-point route used as nav context (arrival check also tests route endpoint)
ROUTE = [
    {'lat': START[0], 'lng': START[1]},
    {'lat': (START[0] + DEST[0]) / 2, 'lng': (START[1] + DEST[1]) / 2},
    {'lat': DEST[0], 'lng': DEST[1]},
]

# T4: destination is 5 m short of the real destination
_T4_DEST = (DEST[0] - 5 / 111_111, DEST[1])

# ── Scenarios ────────────────────────────────────────────────────────────────

SCENARIOS = {
    'T1_direct':        lambda: straight_approach(START, DEST,  WALKING_SPEED, GPS_STEP_SEC),
    'T2_overshoot_10m': lambda: overshoot(START, DEST, 10,      WALKING_SPEED, GPS_STEP_SEC),
    'T3_overshoot_30m': lambda: overshoot(START, DEST, 30,      WALKING_SPEED, GPS_STEP_SEC),
    'T4_stop_5m_short': lambda: straight_approach(START, _T4_DEST, WALKING_SPEED, GPS_STEP_SEC),
    'T5_circle_30m':    lambda: circle_around(DEST, 30, 120,    WALKING_SPEED, GPS_STEP_SEC),
}

# ── Sweep ────────────────────────────────────────────────────────────────────

def test_arrival_sweep(arrival_results):
    """
    Run full arrival_radius × noise sweep over all 5 scenarios.
    Collects results into arrival_results for report generation.
    At the end, runs sanity assertions on the noise-free cases.
    """
    for scenario_name, trace_factory in SCENARIOS.items():
        for arrival_radius in ARRIVAL_RADIUS_SWEEP:
            for sigma in NOISE_SIGMA_SWEEP:
                fired_count = 0
                fire_dists  = []
                dup_count   = 0

                for trial in range(NOISE_TRIALS):
                    trace = trace_factory()
                    if sigma > 0:
                        trace = add_gaussian_noise(
                            trace, sigma_m=sigma, seed=NOISE_SEED_BASE + trial
                        )

                    eng = NavigationEngine(arrival_radius=arrival_radius)
                    eng.set_destination(*DEST)
                    eng.set_route(ROUTE)

                    events   = replay_trace(eng, trace)
                    arrivals = [e for e in events if e.event_type == 'arrival']

                    if arrivals:
                        fired_count += 1
                        fire_dists.append(arrivals[0].data['dist_to_dest'])
                    if len(arrivals) > 1:
                        dup_count += 1

                arrival_results.append({
                    'scenario':        scenario_name,
                    'arrival_radius':  arrival_radius,
                    'noise_sigma':     sigma,
                    'fired_rate':      fired_count / NOISE_TRIALS,
                    'mean_fire_dist_m': (
                        sum(fire_dists) / len(fire_dists) if fire_dists else None
                    ),
                    'duplicate_rate':  dup_count / NOISE_TRIALS,
                })

    # ── Sanity assertions (noise-free baseline) ───────────────────────────
    def _get(scenario, radius, sigma=0):
        return next(
            r for r in arrival_results
            if r['scenario'] == scenario
            and r['arrival_radius'] == radius
            and r['noise_sigma'] == sigma
        )

    # T1 direct approach: must fire 100 % with any tested radius at sigma=0
    for r in ARRIVAL_RADIUS_SWEEP:
        res = _get('T1_direct', r, sigma=0)
        assert res['fired_rate'] == 1.0, (
            f"T1 sigma=0 arrival_radius={r}m: expected 100% fired, got {res['fired_rate']:.0%}"
        )

    # T2 overshoot 10 m: must fire 100% at sigma=0 for any radius ≥ 10 m
    for r in [x for x in ARRIVAL_RADIUS_SWEEP if x >= 10]:
        res = _get('T2_overshoot_10m', r, sigma=0)
        assert res['fired_rate'] == 1.0, (
            f"T2 sigma=0 arrival_radius={r}m: expected 100% fired, got {res['fired_rate']:.0%}"
        )

    # T3 overshoot 30 m: must fire at sigma=0 for any radius ≥ 30 m
    for r in [x for x in ARRIVAL_RADIUS_SWEEP if x >= 30]:
        res = _get('T3_overshoot_30m', r, sigma=0)
        assert res['fired_rate'] == 1.0, (
            f"T3 sigma=0 arrival_radius={r}m: expected 100% fired, got {res['fired_rate']:.0%}"
        )

    # No duplicate firing in any scenario (engine sets state='finished' after first)
    for row in arrival_results:
        assert row['duplicate_rate'] == 0.0, (
            f"Duplicate arrival in {row['scenario']} radius={row['arrival_radius']}m "
            f"sigma={row['noise_sigma']}m"
        )
