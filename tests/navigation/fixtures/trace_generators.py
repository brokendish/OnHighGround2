"""
Synthetic GPS trace generators for navigation parameter sweep tests.

All traces are lists of fixes:
    [{'timestamp': float, 'lat': float, 'lon': float, 'accuracy': float}, ...]

Timestamps are virtual seconds from 0.  No real-time delays involved.
"""

import math
from typing import List, Tuple

import numpy as np

# Type aliases
Coord = Tuple[float, float]   # (lat, lon)
Fix   = dict                  # {'timestamp', 'lat', 'lon', 'accuracy'}
Trace = List[Fix]

_R          = 6_371_000       # Earth radius, metres
_DEFAULT_ACC = 10.0           # GPS accuracy when not specified


# ── Internal geometry helpers ────────────────────────────────────────────────

def _haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    to_r = math.pi / 180
    dl = (lat2 - lat1) * to_r
    dlo = (lon2 - lon1) * to_r
    a = math.sin(dl / 2) ** 2 + math.cos(lat1 * to_r) * math.cos(lat2 * to_r) * math.sin(dlo / 2) ** 2
    return _R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing in radians (north = 0, east = π/2)."""
    dlon = math.radians(lon2 - lon1)
    la1, la2 = math.radians(lat1), math.radians(lat2)
    x = math.sin(dlon) * math.cos(la2)
    y = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(dlon)
    return math.atan2(x, y)


def _advance(lat: float, lon: float, bearing_rad: float, distance_m: float) -> Coord:
    """Return (lat, lon) after moving distance_m along bearing_rad."""
    d  = distance_m / _R
    la = math.radians(lat)
    lo = math.radians(lon)
    la2 = math.asin(
        math.sin(la) * math.cos(d)
        + math.cos(la) * math.sin(d) * math.cos(bearing_rad)
    )
    lo2 = lo + math.atan2(
        math.sin(bearing_rad) * math.sin(d) * math.cos(la),
        math.cos(d) - math.sin(la) * math.sin(la2),
    )
    return math.degrees(la2), math.degrees(lo2)


def _fix(t: float, lat: float, lon: float, acc: float = _DEFAULT_ACC) -> Fix:
    return {'timestamp': t, 'lat': lat, 'lon': lon, 'accuracy': acc}


# ── Public generators ────────────────────────────────────────────────────────

def straight_approach(
    start: Coord,
    dest: Coord,
    speed: float = 1.3,       # m/s (average walking speed)
    step_sec: float = 3.0,
) -> Trace:
    """
    Walk in a straight line from start toward dest at constant speed.
    The trace ends with a fix exactly at dest.
    """
    lat, lon = start
    d_lat, d_lon = dest
    step_m = speed * step_sec
    trace: Trace = []
    t = 0.0

    while True:
        trace.append(_fix(t, lat, lon))
        dist = _haversine(lat, lon, d_lat, d_lon)
        if dist <= step_m:
            break
        brg = _bearing(lat, lon, d_lat, d_lon)
        lat, lon = _advance(lat, lon, brg, step_m)
        t += step_sec

    trace.append(_fix(t + step_sec, d_lat, d_lon))
    return trace


def overshoot(
    start: Coord,
    dest: Coord,
    overshoot_m: float = 30.0,
    speed: float = 1.3,
    step_sec: float = 3.0,
) -> Trace:
    """
    Walk straight from start through dest and continue by overshoot_m beyond it.
    The bearing is fixed at the start→dest direction.
    """
    brg = _bearing(*start, *dest)
    total_m = _haversine(*start, *dest) + overshoot_m
    step_m  = speed * step_sec

    lat, lon = start
    trace: Trace = []
    t = 0.0
    covered = 0.0

    while covered < total_m:
        trace.append(_fix(t, lat, lon))
        step = min(step_m, total_m - covered)
        lat, lon = _advance(lat, lon, brg, step)
        covered += step
        t += step_sec

    trace.append(_fix(t, lat, lon))
    return trace


def circle_around(
    center: Coord,
    radius_m: float = 30.0,
    duration_sec: float = 120.0,
    speed: float = 1.3,
    step_sec: float = 3.0,
) -> Trace:
    """
    Walk in a circle of radius_m around center for duration_sec seconds.
    The angular velocity is derived from speed and circumference.
    First fix is at bearing=0 (north of center).
    """
    clat, clon = center
    circumference  = 2 * math.pi * radius_m
    angular_speed  = (speed / circumference) * 2 * math.pi   # rad/s

    trace: Trace = []
    t = 0.0
    while t <= duration_sec:
        angle   = angular_speed * t
        dlat    = (radius_m * math.cos(angle)) / 111_111
        dlon    = (radius_m * math.sin(angle)) / (111_111 * math.cos(math.radians(clat)))
        trace.append(_fix(t, clat + dlat, clon + dlon))
        t += step_sec

    return trace


def deviate_from_route(
    route: list,
    deviation_m: float = 50.0,
    return_to_route: bool = True,
    deviation_at_frac: float = 0.4,
    speed: float = 1.3,
    step_sec: float = 3.0,
) -> Trace:
    """
    Walk along route up to deviation_at_frac of total distance,
    then move perpendicular by deviation_m, then optionally return and
    continue to route end.

    route: list of {'lat': float, 'lng': float}  (NavigationEngine format)
    Returns a GPS trace in {'lat', 'lon', ...} format.
    """
    if len(route) < 2:
        raise ValueError("Route must have at least 2 waypoints")

    # Build cumulative distances
    cum_dist = [0.0]
    for i in range(len(route) - 1):
        cum_dist.append(cum_dist[-1] + _haversine(
            route[i]['lat'], route[i]['lng'],
            route[i + 1]['lat'], route[i + 1]['lng'],
        ))
    total_dist  = cum_dist[-1]
    dev_at_dist = total_dist * deviation_at_frac

    step_m = speed * step_sec
    trace: Trace = []
    t = 0.0

    # Walk to deviation point
    covered = 0.0
    lat, lon = route[0]['lat'], route[0]['lng']

    for i in range(len(route) - 1):
        a = route[i]
        b = route[i + 1]
        seg_start = cum_dist[i]
        seg_end   = cum_dist[i + 1]
        seg_len   = seg_end - seg_start

        # How far into this segment should we stop?
        if seg_end <= dev_at_dist:
            stop_in_seg = seg_len
        else:
            stop_in_seg = max(0.0, dev_at_dist - seg_start)

        steps = max(1, int(stop_in_seg / step_m))
        brg   = _bearing(a['lat'], a['lng'], b['lat'], b['lng'])
        for j in range(steps):
            trace.append(_fix(t, lat, lon))
            lat, lon = _advance(lat, lon, brg, step_m)
            t += step_sec

        if seg_end > dev_at_dist:
            break

    dev_lat, dev_lon = lat, lon  # position before deviation

    # Compute perpendicular bearing at deviation point
    # Use the bearing to the next waypoint; rotate 90° right
    next_wp_idx = min(int(deviation_at_frac * (len(route) - 1)) + 1, len(route) - 1)
    ref_brg = _bearing(
        route[max(0, next_wp_idx - 1)]['lat'], route[max(0, next_wp_idx - 1)]['lng'],
        route[next_wp_idx]['lat'], route[next_wp_idx]['lng'],
    )
    perp_brg = ref_brg + math.pi / 2

    # Move out by deviation_m
    dev_steps = max(1, round(deviation_m / step_m))
    for _ in range(dev_steps):
        lat, lon = _advance(lat, lon, perp_brg, step_m)
        trace.append(_fix(t, lat, lon))
        t += step_sec

    if return_to_route:
        # Walk back to the deviation-start point on the route
        dist_back = _haversine(lat, lon, dev_lat, dev_lon)
        back_steps = max(1, round(dist_back / step_m))
        back_brg   = _bearing(lat, lon, dev_lat, dev_lon)
        for _ in range(back_steps):
            lat, lon = _advance(lat, lon, back_brg, step_m)
            trace.append(_fix(t, lat, lon))
            t += step_sec

        lat, lon = dev_lat, dev_lon   # snap back to route

        # Continue to route end from deviation waypoint
        start_seg = int(deviation_at_frac * (len(route) - 1))
        for i in range(start_seg, len(route) - 1):
            a   = route[i]
            b   = route[i + 1]
            seg = _haversine(a['lat'], a['lng'], b['lat'], b['lng'])
            steps = max(1, round(seg / step_m))
            brg   = _bearing(a['lat'], a['lng'], b['lat'], b['lng'])
            for _ in range(steps):
                lat, lon = _advance(lat, lon, brg, step_m)
                trace.append(_fix(t, lat, lon))
                t += step_sec

    return trace


def add_gaussian_noise(
    trace: Trace,
    sigma_m: float = 10.0,
    accuracy_field: bool = True,
    seed: int = 42,
) -> Trace:
    """
    Add independent Gaussian position noise (σ metres) to each fix.

    Args:
        trace:          Input trace (not modified in place).
        sigma_m:        Noise standard deviation in metres.
                        Urban typical: 5-15 m; canyon/indoor: 20-30 m.
        accuracy_field: When True, set accuracy = 2 × sigma_m (≈ 95th pct).
        seed:           RNG seed for reproducibility (numpy default_rng).

    Returns: new trace with noise applied.
    """
    rng   = np.random.default_rng(seed)
    noisy: Trace = []
    for fix in trace:
        dlat_m = rng.normal(0.0, sigma_m)
        dlon_m = rng.normal(0.0, sigma_m)
        dlat   = dlat_m / 111_111
        dlon   = dlon_m / (111_111 * math.cos(math.radians(fix['lat'])))
        nf     = fix.copy()
        nf['lat'] = fix['lat'] + dlat
        nf['lon'] = fix['lon'] + dlon
        if accuracy_field:
            nf['accuracy'] = sigma_m * 2   # 2σ ≈ 95% confidence interval
        noisy.append(nf)
    return noisy


def add_gps_loss(
    trace: Trace,
    start_sec: float,
    duration_sec: float,
) -> Trace:
    """
    Remove fixes in [start_sec, start_sec + duration_sec] to simulate GPS loss
    (e.g., tunnel, underground).  Timestamps outside the loss window are unchanged.
    """
    end_sec = start_sec + duration_sec
    return [f for f in trace if not (start_sec <= f['timestamp'] <= end_sec)]
