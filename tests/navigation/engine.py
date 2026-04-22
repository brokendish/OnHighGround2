"""
Python port of the navigation state machine from frontend/js/navigation.js.

Each function documents the corresponding JS source location so that any
divergence can be traced back to the original implementation.

Coordinate format follows the JS convention: {'lat': float, 'lng': float}
(note 'lng', not 'lon') for route waypoints. Destination uses 'lon' to
match the rest of the Python codebase.
"""

import math
from dataclasses import dataclass, field
from typing import Optional


# ── Haversine distance ──────────────────────────────────────────────────────
# JS source: navigation.js:149-157  _navHaversine(lat1, lon1, lat2, lon2)
def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Return great-circle distance in metres between two WGS-84 coordinates."""
    R = 6_371_000
    to_rad = math.pi / 180
    d_lat = (lat2 - lat1) * to_rad
    d_lon = (lon2 - lon1) * to_rad
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(lat1 * to_rad) * math.cos(lat2 * to_rad)
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Project point onto segment ──────────────────────────────────────────────
# JS source: navigation.js:1298-1306  _navProjectOnSegment(p, a, b)
def project_on_segment(p: dict, a: dict, b: dict) -> dict:
    """
    Return the closest point on segment [a, b] to point p.
    All coords use {'lat': float, 'lng': float}.
    Returns {'point': {'lat', 'lng'}, 't': float} where t in [0, 1].
    """
    dx = b['lng'] - a['lng']
    dy = b['lat'] - a['lat']
    len2 = dx * dx + dy * dy
    if len2 == 0:
        return {'point': a, 't': 0.0}
    t = max(0.0, min(1.0,
        ((p['lng'] - a['lng']) * dx + (p['lat'] - a['lat']) * dy) / len2
    ))
    return {
        'point': {'lat': a['lat'] + t * dy, 'lng': a['lng'] + t * dx},
        't': t,
    }


# ── Closest point on route ──────────────────────────────────────────────────
# JS source: navigation.js:1310-1323  _navFindClosestOnRoute(coords, lat, lon)
def find_closest_on_route(coords: list, lat: float, lon: float) -> Optional[dict]:
    """
    Find the nearest point on a polyline to (lat, lon).

    Returns:
        {'snapped_point': {'lat', 'lng'}, 'segment_index': int,
         'route_offset_meters': float}
        or None if coords has fewer than 2 points.
    """
    if not coords or len(coords) < 2:
        return None
    p = {'lat': lat, 'lng': lon}
    min_dist = float('inf')
    best = None
    for i in range(len(coords) - 1):
        proj = project_on_segment(p, coords[i], coords[i + 1])
        d = haversine(lat, lon, proj['point']['lat'], proj['point']['lng'])
        if d < min_dist:
            min_dist = d
            best = {
                'snapped_point': proj['point'],
                'segment_index': i,
                'route_offset_meters': d,
            }
    return best


# ── Remaining route distance ────────────────────────────────────────────────
# JS source: navigation.js:1327-1347  _remainingRouteDistance(lat, lon)
# Note: JS reads navActiveRoute from module state; here coords is passed in.
def remaining_route_distance(coords: list, lat: float, lon: float) -> Optional[dict]:
    """
    Compute remaining distance along the route from the nearest snap point.

    Returns:
        {'remaining_distance_meters': float, 'route_offset_meters': float}
        or None if route is too short or no snap found.
    """
    if not coords or len(coords) < 2:
        return None
    closest = find_closest_on_route(coords, lat, lon)
    if closest is None:
        return None
    seg_i = closest['segment_index']
    # Distance from snapped point to the end of the current segment
    remaining = haversine(
        closest['snapped_point']['lat'], closest['snapped_point']['lng'],
        coords[seg_i + 1]['lat'], coords[seg_i + 1]['lng'],
    )
    # Add full lengths of all subsequent segments
    for i in range(seg_i + 1, len(coords) - 1):
        remaining += haversine(
            coords[i]['lat'], coords[i]['lng'],
            coords[i + 1]['lat'], coords[i + 1]['lng'],
        )
    return {
        'remaining_distance_meters': remaining,
        'route_offset_meters': closest['route_offset_meters'],
    }


# ── Event record ────────────────────────────────────────────────────────────

@dataclass
class NavEvent:
    """One navigation event emitted by the engine during trace replay."""
    event_type: str   # 'arrival' | 'off_route_warning' | 'reroute_triggered' | 'back_on_route'
    timestamp: float  # virtual seconds since trace start
    data: dict = field(default_factory=dict)

    def __repr__(self):
        return f"NavEvent({self.event_type!r}, t={self.timestamp:.1f}s, {self.data})"


# ── Navigation engine ───────────────────────────────────────────────────────

class NavigationEngine:
    """
    Simulates the navigation position-update state machine from navigation.js.

    Default parameter values mirror the JS constants (navigation.js:12-37).
    All distance values are in metres; time values in seconds.

    Debounce approximation:
        JS uses setTimeout which fires independently of GPS updates.
        Here, the timer fires on the first GPS update after virtual-time
        elapsed >= debounce_sec. This introduces at most one update-interval
        of additional delay compared to real JS behaviour.
    """

    # Default values — mirror navigation.js:12-37
    _ARRIVAL_M_DEFAULT         = 40
    _REROUTE_THRESHOLD_DEFAULT = 30
    _OFF_ROUTE_M_DEFAULT       = 20
    _CONSECUTIVE_DEFAULT       = 3
    _DEBOUNCE_SEC_DEFAULT      = 3.0
    _MIN_DELTA_M_DEFAULT       = 8
    _ACCURACY_MULTIPLIER       = 1.5   # navigation.js:1610  accuracy * 1.5

    def __init__(
        self,
        arrival_radius: float    = _ARRIVAL_M_DEFAULT,
        reroute_threshold: float = _REROUTE_THRESHOLD_DEFAULT,
        off_route_m: float       = _OFF_ROUTE_M_DEFAULT,
        consecutive_required: int = _CONSECUTIVE_DEFAULT,
        debounce_sec: float      = _DEBOUNCE_SEC_DEFAULT,
        min_delta_m: float       = _MIN_DELTA_M_DEFAULT,
    ):
        self.arrival_radius       = arrival_radius
        self.reroute_threshold    = reroute_threshold
        self.off_route_m          = off_route_m
        self.consecutive_required = consecutive_required
        self.debounce_sec         = debounce_sec
        self.min_delta_m          = min_delta_m

        self._destination: Optional[dict] = None  # {'lat': float, 'lon': float}
        self._route: Optional[list] = None        # [{'lat': float, 'lng': float}, ...]
        self._current_location: Optional[dict] = None
        self._state: str = 'active'               # 'active' | 'warning' | 'finished'
        self._off_route_count: int = 0
        self._debounce_start_ts: Optional[float] = None

    def reset(self):
        """Reset mutable state; keeps parameter values."""
        self._destination = None
        self._route = None
        self._current_location = None
        self._state = 'active'
        self._off_route_count = 0
        self._debounce_start_ts = None

    def set_destination(self, lat: float, lon: float):
        self._destination = {'lat': lat, 'lon': lon}

    def set_route(self, coords: list):
        """coords: [{'lat': float, 'lng': float}, ...]"""
        self._route = coords

    def feed(self, lat: float, lon: float, accuracy: float, timestamp: float) -> list:
        """
        Process one GPS fix; return list of NavEvent objects.

        Mirrors _onNavPosition (navigation.js:1604-1755).
        """
        if self._state == 'finished':
            return []

        events = []

        # ── Arrival check (before min-delta filter) ───────────────────────
        # JS: navigation.js:1607-1633
        if self._destination is not None:
            effective_radius = max(
                self.arrival_radius,
                accuracy * self._ACCURACY_MULTIPLIER,
            )
            arr_dist = haversine(
                lat, lon,
                self._destination['lat'], self._destination['lon'],
            )
            if arr_dist <= effective_radius:
                events.append(NavEvent('arrival', timestamp, {
                    'dist_to_dest': arr_dist,
                    'effective_radius': effective_radius,
                    'trigger': 'destination',
                }))
                self._state = 'finished'
                return events

            # Route-endpoint fallback (JS: navigation.js:1621-1632)
            if self._route and len(self._route) >= 1:
                last = self._route[-1]
                last_dist = haversine(lat, lon, last['lat'], last['lng'])
                if last_dist <= effective_radius:
                    events.append(NavEvent('arrival', timestamp, {
                        'dist_to_dest': last_dist,
                        'effective_radius': effective_radius,
                        'trigger': 'route_endpoint',
                    }))
                    self._state = 'finished'
                    return events

        # ── Min-delta filter (JS: navigation.js:1635-1639) ────────────────
        if self._current_location is not None:
            moved = haversine(
                self._current_location['lat'], self._current_location['lon'],
                lat, lon,
            )
            if moved < self.min_delta_m:
                return events
        self._current_location = {'lat': lat, 'lon': lon}

        # ── Off-route / reroute check (JS: navigation.js:1709-1754) ──────
        if self._route is not None:
            result = remaining_route_distance(self._route, lat, lon)
            if result is not None:
                offset_m = result['route_offset_meters']

                # Check if pending debounce timer has expired
                if (self._debounce_start_ts is not None
                        and timestamp - self._debounce_start_ts >= self.debounce_sec
                        and self._off_route_count >= self.consecutive_required):
                    events.append(NavEvent('reroute_triggered', timestamp, {
                        'offset_m': offset_m,
                        'off_route_count': self._off_route_count,
                        'debounce_delay_sec': timestamp - self._debounce_start_ts,
                    }))
                    self._debounce_start_ts = None
                    self._off_route_count = 0
                    if self._state == 'warning':
                        self._state = 'active'

                if offset_m >= self.off_route_m:
                    self._off_route_count += 1
                    if (self._off_route_count >= self.consecutive_required
                            and self._state == 'active'):
                        self._state = 'warning'
                        events.append(NavEvent('off_route_warning', timestamp, {
                            'offset_m': offset_m,
                            'off_route_count': self._off_route_count,
                        }))
                    if (offset_m >= self.reroute_threshold
                            and self._debounce_start_ts is None):
                        self._debounce_start_ts = timestamp
                else:
                    if self._off_route_count > 0:
                        if self._state == 'warning':
                            self._state = 'active'
                            events.append(NavEvent('back_on_route', timestamp, {
                                'offset_m': offset_m,
                            }))
                        self._off_route_count = 0
                        self._debounce_start_ts = None

        return events


# ── Trace replay ────────────────────────────────────────────────────────────

def replay_trace(engine: NavigationEngine, trace: list, params: dict = None) -> list:
    """
    Replay a GPS trace through a NavigationEngine.

    Args:
        engine: pre-configured NavigationEngine (destination + route already set)
        trace:  list of {'timestamp': float, 'lat': float, 'lon': float,
                         'accuracy': float}
        params: optional dict of engine attribute overrides applied before replay

    Returns:
        list of NavEvent objects emitted during the replay
    """
    if params:
        for k, v in params.items():
            if hasattr(engine, k):
                setattr(engine, k, v)

    all_events: list = []
    for fix in trace:
        evs = engine.feed(
            lat=fix['lat'],
            lon=fix['lon'],
            accuracy=fix.get('accuracy', 10.0),
            timestamp=fix['timestamp'],
        )
        all_events.extend(evs)
    return all_events
