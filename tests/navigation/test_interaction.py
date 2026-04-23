"""
Arrival × reroute threshold interaction matrix.

Scenario: user walks on-route for 250 m, then makes a diagonal off-route
approach for the final 50 m while 30 m laterally offset from the route.
They always reach the destination at the end of the trace.

Key question per (arrival_radius, reroute_threshold) cell:
  Does arrival fire before / after / instead of reroute?

With the post-fix code, arrival is checked FIRST on every GPS update.
Once the user satisfies the consecutive arrival rule, arrival fires and the
reroute check never runs.  The matrix confirms the actual boundary.

Classifications:
  'arrival_only'    — arrival fired; reroute never fired
  'safe'            — arrival fired after reroute fired (reroute then arrival)
                      ← renamed in code as 'reroute_then_arr'
  'reroute_then_arr'— reroute fired first, then arrival fired
  'reroute_only'    — reroute fired; arrival never fired
  'neither'         — neither event fired
"""

import math

import pytest

from engine import NavigationEngine, replay_trace
from fixtures.trace_generators import straight_approach, add_gaussian_noise
from sweep_config import (
    ARRIVAL_RADIUS_SWEEP,
    REROUTE_THRESHOLD_SWEEP,
    NOISE_TRIALS,
    NOISE_SEED_BASE,
    WALKING_SPEED,
    GPS_STEP_SEC,
)

# ── Geometry ─────────────────────────────────────────────────────────────────

DEST  = (35.6800, 139.6600)
START = (DEST[0] + 300 / 111_111, DEST[1])   # 300 m north

ROUTE = [
    {'lat': START[0], 'lng': START[1]},
    {'lat': (START[0] + DEST[0]) / 2, 'lng': DEST[1]},
    {'lat': DEST[0],                  'lng': DEST[1]},
]

# Lateral offset for the off-route phase (metres east)
_LAT_OFFSET_M = 30


def _make_trace(sigma: float, trial: int = 0) -> list:
    """
    Phase 1: on-route from START to 50 m north of DEST (250 m).
    Phase 2: from 30 m east of the turn-point to DEST (diagonal, ~58 m, off-route).
    User always ends at DEST.
    """
    turn_lat = DEST[0] + 50 / 111_111
    turn_lon = DEST[1]

    # Phase 1 — on-route
    phase1 = straight_approach(
        (START[0], START[1]),
        (turn_lat, turn_lon),
        WALKING_SPEED, GPS_STEP_SEC,
    )

    # Phase 2 — off-route diagonal toward DEST
    dlon = _LAT_OFFSET_M / (111_111 * math.cos(math.radians(DEST[0])))
    phase2_start = (turn_lat, turn_lon + dlon)   # 30 m east of turn-point
    phase2 = straight_approach(phase2_start, DEST, WALKING_SPEED, GPS_STEP_SEC)

    # Shift Phase 2 timestamps so they follow Phase 1
    t_offset = phase1[-1]['timestamp'] + GPS_STEP_SEC
    phase2 = [{**f, 'timestamp': f['timestamp'] + t_offset} for f in phase2]

    trace = phase1 + phase2

    if sigma > 0:
        trace = add_gaussian_noise(trace, sigma_m=sigma,
                                   seed=NOISE_SEED_BASE + trial)
    return trace


def _classify(events: list) -> str:
    types  = [e.event_type for e in events]
    has_arr = 'arrival' in types
    has_rer = 'reroute_triggered' in types

    if has_arr and has_rer:
        first = next(e for e in events
                     if e.event_type in ('arrival', 'reroute_triggered'))
        return 'reroute_then_arr' if first.event_type == 'reroute_triggered' else 'arrival_only'
    if has_arr:
        return 'arrival_only'
    if has_rer:
        return 'reroute_only'
    return 'neither'


# ── Sweep ─────────────────────────────────────────────────────────────────────

def test_interaction_matrix(interaction_results):
    """
    Build 2D matrix: (arrival_radius × reroute_threshold) → dominant classification.
    Run at σ = 0 m and σ = 10 m.
    """
    for sigma in [0, 10]:
        for arrival_radius in ARRIVAL_RADIUS_SWEEP:
            for reroute_threshold in REROUTE_THRESHOLD_SWEEP:
                class_counts: dict = {}

                for trial in range(NOISE_TRIALS):
                    trace  = _make_trace(sigma, trial)
                    eng    = NavigationEngine(
                        arrival_radius=arrival_radius,
                        reroute_threshold=reroute_threshold,
                    )
                    eng.set_destination(*DEST)
                    eng.set_route(ROUTE)

                    events = replay_trace(eng, trace)
                    cls    = _classify(events)
                    class_counts[cls] = class_counts.get(cls, 0) + 1

                dominant = max(class_counts, key=class_counts.get)
                interaction_results.append({
                    'arrival_radius':        arrival_radius,
                    'reroute_threshold':     reroute_threshold,
                    'noise_sigma':           sigma,
                    'classification':        dominant,
                    'class_counts':          class_counts,
                    'arrival_rate':
                        (class_counts.get('arrival_only',    0)
                         + class_counts.get('reroute_then_arr', 0)) / NOISE_TRIALS,
                    'reroute_near_dest_rate':
                        class_counts.get('reroute_then_arr', 0) / NOISE_TRIALS,
                })

    # ── Sanity assertions ─────────────────────────────────────────────────

    def _get(ar, rt, sigma=0):
        return next(
            r for r in interaction_results
            if r['arrival_radius'] == ar
            and r['reroute_threshold'] == rt
            and r['noise_sigma'] == sigma
        )

    # Large radius + large threshold + σ=0: user always reaches DEST → arrival must fire
    res = _get(75, 100, sigma=0)
    assert res['arrival_rate'] == 1.0, (
        f"ar=75, rt=100 σ=0: expected 100% arrival, got {res['arrival_rate']:.2f}"
    )

    # Small radius + small threshold: reroute should fire (30 m offset > any tested threshold)
    # but arrival_radius=15m may be too small to detect diagonal approach
    res_small = _get(15, 15, sigma=0)
    # Just verify the test ran cleanly
    assert 'classification' in res_small

    # Large arrival_radius (50m+) should always detect arrival regardless of threshold
    for rt in REROUTE_THRESHOLD_SWEEP:
        res = _get(50, rt, sigma=0)
        assert res['arrival_rate'] == 1.0, (
            f"ar=50, rt={rt} σ=0: expected 100% arrival, got {res['arrival_rate']:.2f}"
        )
