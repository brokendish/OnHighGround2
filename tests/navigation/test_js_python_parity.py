"""
JS ↔ Python parity tests for navigation math functions.

For each pure-math function in frontend/js/navigation.js, this module:
  1. Calls the Python implementation in engine.py
  2. Calls the JS implementation via parity_harness.js through Node.js subprocess
  3. Asserts the results match within floating-point tolerance

Since both JS and Python use IEEE 754 double-precision arithmetic and the
operations are identical, results should agree to ~15 significant digits.
Tolerance is set to 1e-6 m (1 µm) to catch any algorithmic divergence while
being robust against the final ULP of transcendental functions (sin/cos/atan2).

JS source: frontend/js/navigation.js @ commit c19fb58
Harness:   tests/navigation/js_parity/parity_harness.js
"""

import json
import subprocess
from pathlib import Path

import pytest

from engine import (
    haversine,
    project_on_segment,
    find_closest_on_route,
    remaining_route_distance,
)

# ── Harness helpers ───────────────────────────────────────────────────────────

HARNESS = Path(__file__).parent / "js_parity" / "parity_harness.js"
TOLS = 1e-6  # 1 µm — catches algorithmic errors; robust against FP rounding


def _call_js(function: str, args: dict):
    """Call parity_harness.js via Node.js and return the parsed result."""
    payload = json.dumps({"function": function, "args": args})
    proc = subprocess.run(
        ["node", str(HARNESS)],
        input=payload,
        capture_output=True,
        text=True,
        timeout=5,
    )
    assert proc.returncode == 0, f"Node.js harness exited {proc.returncode}: {proc.stderr}"
    response = json.loads(proc.stdout)
    assert "error" not in response, f"JS harness error: {response['error']}"
    return response["result"]


# ── Haversine ─────────────────────────────────────────────────────────────────
# JS: navigation.js:149-157  _navHaversine

HAVERSINE_CASES = [
    (35.6762, 139.6503, 35.6762, 139.6503, "identical points → 0 m"),
    (35.6762, 139.6503, 35.6862, 139.6503, "~1.1 km north"),
    (35.6762, 139.6503, 35.6762, 139.6603, "~0.9 km east"),
    (35.6762, 139.6503, 35.6792, 139.6533, "~40 m diagonal (arrival-scale)"),
    (35.6762, 139.6503, 35.6764, 139.6505, "~25 m (boundary near arrival radius)"),
    (0.0, 0.0, 0.0, 180.0, "antipodal"),
    (90.0, 0.0, -90.0, 0.0, "pole to pole"),
    (35.6762, 139.6503, 35.6762 + 1e-7, 139.6503, "sub-millimetre separation"),
]


@pytest.mark.parametrize("lat1,lon1,lat2,lon2,desc", HAVERSINE_CASES)
def test_haversine_parity(lat1, lon1, lat2, lon2, desc):
    py = haversine(lat1, lon1, lat2, lon2)
    js = _call_js("haversine", {"lat1": lat1, "lon1": lon1, "lat2": lat2, "lon2": lon2})
    assert abs(py - js) < TOLS, (
        f"{desc}: Python={py:.10f} m, JS={js:.10f} m, diff={abs(py - js):.2e} m"
    )


# ── project_on_segment ────────────────────────────────────────────────────────
# JS: navigation.js:1298-1306  _navProjectOnSegment

# Segment A→B for all projection cases
_SEG_A = {"lat": 35.676, "lng": 139.650}
_SEG_B = {"lat": 35.677, "lng": 139.651}

PROJECT_CASES = [
    ({"lat": 35.676,   "lng": 139.650},  "p = segment start → t=0"),
    ({"lat": 35.677,   "lng": 139.651},  "p = segment end → t=1"),
    ({"lat": 35.6765,  "lng": 139.6505}, "p at midpoint → t≈0.5"),
    ({"lat": 35.675,   "lng": 139.649},  "p before start, clamps to a"),
    ({"lat": 35.679,   "lng": 139.653},  "p beyond end, clamps to b"),
    ({"lat": 35.6763,  "lng": 139.6507}, "p perpendicular off segment"),
    ({"lat": 35.676,   "lng": 139.650},  "zero-length segment (a == b)"),  # handled separately
]


@pytest.mark.parametrize("p,desc", PROJECT_CASES[:-1])
def test_project_on_segment_parity(p, desc):
    py = project_on_segment(p, _SEG_A, _SEG_B)
    js = _call_js("project_on_segment", {"p": p, "a": _SEG_A, "b": _SEG_B})
    assert abs(py["t"] - js["t"]) < TOLS, (
        f"{desc}: t  Python={py['t']:.10f}, JS={js['t']:.10f}"
    )
    assert abs(py["point"]["lat"] - js["point"]["lat"]) < TOLS, (
        f"{desc}: lat Python={py['point']['lat']:.10f}, JS={js['point']['lat']:.10f}"
    )
    assert abs(py["point"]["lng"] - js["point"]["lng"]) < TOLS, (
        f"{desc}: lng Python={py['point']['lng']:.10f}, JS={js['point']['lng']:.10f}"
    )


def test_project_on_segment_zero_length():
    """Zero-length segment: both implementations should return the segment point."""
    p = {"lat": 35.678, "lng": 139.652}
    a = b = {"lat": 35.676, "lng": 139.650}
    py = project_on_segment(p, a, b)
    js = _call_js("project_on_segment", {"p": p, "a": a, "b": b})
    assert abs(py["t"] - js["t"]) < TOLS
    assert abs(py["point"]["lat"] - js["point"]["lat"]) < TOLS
    assert abs(py["point"]["lng"] - js["point"]["lng"]) < TOLS


# ── find_closest_on_route ─────────────────────────────────────────────────────
# JS: navigation.js:1310-1323  _navFindClosestOnRoute

_ROUTE_3PT = [
    {"lat": 35.676, "lng": 139.650},
    {"lat": 35.677, "lng": 139.651},
    {"lat": 35.678, "lng": 139.652},
]

CLOSEST_CASES = [
    (_ROUTE_3PT, 35.6765,  139.6505,  "midpoint of first segment → seg 0"),
    (_ROUTE_3PT, 35.6775,  139.6515,  "midpoint of second segment → seg 1"),
    (_ROUTE_3PT, 35.676,   139.650,   "exactly at route start"),
    (_ROUTE_3PT, 35.678,   139.652,   "exactly at route end"),
    (_ROUTE_3PT, 35.674,   139.648,   "far before start, clamps to seg 0"),
    (_ROUTE_3PT, 35.680,   139.655,   "far beyond end, clamps to seg 1"),
    (_ROUTE_3PT, 35.6763,  139.6510,  "perpendicular off seg 0"),
    (_ROUTE_3PT, 35.6780,  139.6495,  "perpendicular off seg 1 from west"),
]


@pytest.mark.parametrize("coords,lat,lon,desc", CLOSEST_CASES)
def test_find_closest_on_route_parity(coords, lat, lon, desc):
    py = find_closest_on_route(coords, lat, lon)
    js = _call_js("find_closest_on_route", {"coords": coords, "lat": lat, "lon": lon})
    assert py is not None and js is not None, f"{desc}: unexpected None"
    assert py["segment_index"] == js["segment_index"], (
        f"{desc}: segment_index Python={py['segment_index']}, JS={js['segment_index']}"
    )
    assert abs(py["route_offset_meters"] - js["route_offset_meters"]) < TOLS, (
        f"{desc}: offset Python={py['route_offset_meters']:.10f}, JS={js['route_offset_meters']:.10f}"
    )
    assert abs(py["snapped_point"]["lat"] - js["snapped_point"]["lat"]) < TOLS, (
        f"{desc}: snapped lat mismatch"
    )
    assert abs(py["snapped_point"]["lng"] - js["snapped_point"]["lng"]) < TOLS, (
        f"{desc}: snapped lng mismatch"
    )


def test_find_closest_on_route_too_short():
    """Single-point route returns None in both implementations."""
    single = [{"lat": 35.676, "lng": 139.650}]
    assert find_closest_on_route(single, 35.676, 139.650) is None
    assert _call_js("find_closest_on_route", {"coords": single, "lat": 35.676, "lon": 139.650}) is None


# ── remaining_route_distance ──────────────────────────────────────────────────
# JS: navigation.js:1327-1347  _remainingRouteDistance

REMAINING_CASES = [
    (_ROUTE_3PT, 35.676,   139.650,   "at start → full route length"),
    (_ROUTE_3PT, 35.6765,  139.6505,  "midpoint seg 0 → half seg0 + full seg1"),
    (_ROUTE_3PT, 35.678,   139.652,   "at end → ~0 remaining"),
    (_ROUTE_3PT, 35.6775,  139.6515,  "midpoint seg 1 → half seg1"),
    (_ROUTE_3PT, 35.6763,  139.6510,  "off-route perpendicular seg 0"),
    (_ROUTE_3PT, 35.680,   139.655,   "beyond end, clamped to seg 1 end"),
]


@pytest.mark.parametrize("coords,lat,lon,desc", REMAINING_CASES)
def test_remaining_route_distance_parity(coords, lat, lon, desc):
    py = remaining_route_distance(coords, lat, lon)
    js = _call_js("remaining_route_distance", {"coords": coords, "lat": lat, "lon": lon})
    assert py is not None and js is not None, f"{desc}: unexpected None"
    assert abs(py["remaining_distance_meters"] - js["remaining_distance_meters"]) < TOLS, (
        f"{desc}: remaining  Python={py['remaining_distance_meters']:.8f} m"
        f", JS={js['remaining_distance_meters']:.8f} m"
        f", diff={abs(py['remaining_distance_meters'] - js['remaining_distance_meters']):.2e} m"
    )
    assert abs(py["route_offset_meters"] - js["route_offset_meters"]) < TOLS, (
        f"{desc}: offset  Python={py['route_offset_meters']:.8f} m"
        f", JS={js['route_offset_meters']:.8f} m"
    )
