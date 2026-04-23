import math

from engine import NavigationEngine, replay_trace


DEST = (35.6800, 139.6600)
START = (DEST[0] + 120 / 111_111, DEST[1])
ROUTE = [
    {"lat": START[0], "lng": START[1]},
    {"lat": (START[0] + DEST[0]) / 2, "lng": DEST[1]},
    {"lat": DEST[0], "lng": DEST[1]},
]


def _fix(north_m: float, east_m: float = 0, t: float = 0, accuracy: float = 10) -> dict:
    lon_scale = 111_111 * math.cos(math.radians(DEST[0]))
    return {
        "timestamp": t,
        "lat": DEST[0] + north_m / 111_111,
        "lon": DEST[1] + east_m / lon_scale,
        "accuracy": accuracy,
    }


def _engine() -> NavigationEngine:
    eng = NavigationEngine()
    eng.set_destination(*DEST)
    eng.set_route(ROUTE)
    return eng


def test_arrival_requires_two_consecutive_fixes_inside_12m():
    eng = _engine()
    trace = [
        _fix(20, t=0),
        _fix(10, t=3),
        _fix(11, t=6),
    ]

    events = replay_trace(eng, trace)

    arrivals = [e for e in events if e.event_type == "arrival"]
    assert len(arrivals) == 1
    assert arrivals[0].data["arrival_counter"] == 2
    assert arrivals[0].data["dist_to_dest"] <= 12


def test_single_gps_jitter_inside_arrival_radius_does_not_arrive():
    eng = _engine()
    trace = [
        _fix(20, t=0),
        _fix(10, t=3),
        _fix(18, t=6),
    ]

    events = replay_trace(eng, trace)

    assert "arrival" not in [e.event_type for e in events]


def test_low_accuracy_arrival_is_more_conservative():
    eng = _engine()
    trace = [
        _fix(10, t=0, accuracy=35),
        _fix(10, t=3, accuracy=35),
        _fix(7, t=6, accuracy=35),
        _fix(7, t=9, accuracy=35),
        _fix(7, t=12, accuracy=35),
    ]

    events = replay_trace(eng, trace)

    arrivals = [e for e in events if e.event_type == "arrival"]
    assert len(arrivals) == 1
    assert arrivals[0].data["arrival_radius"] == 8
    assert arrivals[0].data["arrival_counter"] == 3


def test_near_destination_off_route_can_trigger_reroute_before_arrival():
    eng = _engine()
    trace = [
        _fix(45, east_m=20, t=0),
        _fix(35, east_m=20, t=3),
        _fix(25, east_m=20, t=6),
        _fix(15, east_m=20, t=9),
    ]

    events = replay_trace(eng, trace)

    reroutes = [e for e in events if e.event_type == "reroute_triggered"]
    assert len(reroutes) == 1
    assert reroutes[0].data["near_goal"] is True
    assert reroutes[0].data["threshold_m"] == 18


def test_reroute_state_recovers_and_can_trigger_again_after_failure_path():
    eng = _engine()
    trace = [
        _fix(45, east_m=20, t=0),
        _fix(35, east_m=20, t=3),
        _fix(25, east_m=20, t=6),
        _fix(25, east_m=20, t=9),
        _fix(45, east_m=20, t=15),
        _fix(35, east_m=20, t=18),
        _fix(25, east_m=20, t=21),
        _fix(15, east_m=20, t=24),
    ]

    events = replay_trace(eng, trace)

    reroutes = [e for e in events if e.event_type == "reroute_triggered"]
    assert len(reroutes) == 2
