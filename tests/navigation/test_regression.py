"""
Field-trace regression tests.

Loads GPS traces recorded during field tests from
data/test_fixtures/gps_traces/field_tests/*.yaml
and replays them through NavigationEngine, asserting outcomes
described in each trace's meta.yaml.

Trace format (YAML):
  meta:
    date: "2026-05-01"
    location: "Shibuya → Yoyogi Park"
    expected_arrival: true           # arrival event must fire
    expected_reroute: false          # reroute must NOT fire
    notes: "Direct walk, no deviation"
  route:
    - {lat: 35.6xxx, lng: 139.7xxx}
    - ...
  trace:
    - {lat: 35.6xxx, lon: 139.7xxx, accuracy: 8.0, timestamp: 0.0}
    - ...
  destination:
    lat: 35.6xxx
    lon: 139.7xxx

If no trace files are found, the test module is skipped with an
informative message pointing to field_test_protocol.md.
"""

import yaml
import pytest
from pathlib import Path

from engine import NavigationEngine, replay_trace
from sweep_config import CURRENT_ARRIVAL_RADIUS, CURRENT_REROUTE_THRESHOLD

FIXTURE_DIR = Path(__file__).parents[2] / "data/test_fixtures/gps_traces/field_tests"


def _load_traces():
    if not FIXTURE_DIR.exists():
        return []
    return sorted(FIXTURE_DIR.glob("*.yaml"))


_trace_files = _load_traces()


@pytest.mark.skipif(
    len(_trace_files) == 0,
    reason=(
        f"No field trace files found in {FIXTURE_DIR}. "
        "Run a field test per docs/field_test_protocol.md and save traces as YAML."
    ),
)
@pytest.mark.parametrize("trace_path", _trace_files, ids=lambda p: p.stem)
def test_field_trace_regression(trace_path):
    """Replay a field-recorded GPS trace and assert expected events."""
    with open(trace_path) as f:
        data = yaml.safe_load(f)

    meta  = data["meta"]
    route = data["route"]
    dest  = data["destination"]
    raw_trace = data["trace"]

    # Normalise key name: field traces may use 'lon' or 'lng'
    trace = []
    for pt in raw_trace:
        entry = dict(pt)
        if "lng" in entry and "lon" not in entry:
            entry["lon"] = entry.pop("lng")
        trace.append(entry)

    eng = NavigationEngine(
        arrival_radius=CURRENT_ARRIVAL_RADIUS,
        reroute_threshold=CURRENT_REROUTE_THRESHOLD,
    )
    eng.set_destination(dest["lat"], dest["lon"])
    eng.set_route(route)

    events = replay_trace(eng, trace)
    event_types = [e.event_type for e in events]

    if meta.get("expected_arrival", True):
        assert "arrival" in event_types, (
            f"{trace_path.name}: expected arrival event but it did not fire. "
            f"Events: {event_types}"
        )

    if not meta.get("expected_reroute", True):
        assert "reroute_triggered" not in event_types, (
            f"{trace_path.name}: unexpected reroute fired. "
            f"Events: {event_types}"
        )
