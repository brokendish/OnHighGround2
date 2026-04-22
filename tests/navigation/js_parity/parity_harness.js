/**
 * Node.js harness that exposes pure navigation math functions for parity testing.
 *
 * Functions are copied verbatim from frontend/js/navigation.js at commit c19fb58.
 * Source line references are noted inline for each function.
 *
 * Input:  JSON via stdin  { "function": "<name>", "args": { ... } }
 * Output: JSON via stdout { "result": <value> }  or  { "error": "<message>" }
 */

// ── _navHaversine (navigation.js:149-157) ────────────────────────────────────
function _navHaversine(lat1, lon1, lat2, lon2) {
    const R = 6371000;
    const toRad = x => x * Math.PI / 180;
    const dLat = toRad(lat2 - lat1);
    const dLon = toRad(lon2 - lon1);
    const a = Math.sin(dLat / 2) ** 2
            + Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
    return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

// ── _navProjectOnSegment (navigation.js:1298-1306) ───────────────────────────
function _navProjectOnSegment(p, a, b) {
    const dx = b.lng - a.lng, dy = b.lat - a.lat;
    const len2 = dx * dx + dy * dy;
    if (len2 === 0) return { point: a, t: 0 };
    const t = Math.max(0, Math.min(1,
        ((p.lng - a.lng) * dx + (p.lat - a.lat) * dy) / len2
    ));
    return { point: { lat: a.lat + t * dy, lng: a.lng + t * dx }, t };
}

// ── _navFindClosestOnRoute (navigation.js:1310-1323) ─────────────────────────
function _navFindClosestOnRoute(coords, lat, lon) {
    if (!coords || coords.length < 2) return null;
    const p = { lat, lng: lon };
    let minDist = Infinity, best = null;
    for (let i = 0; i < coords.length - 1; i++) {
        const proj = _navProjectOnSegment(p, coords[i], coords[i + 1]);
        const d = _navHaversine(lat, lon, proj.point.lat, proj.point.lng);
        if (d < minDist) {
            minDist = d;
            best = { snappedPoint: proj.point, segmentIndex: i, routeOffsetMeters: d };
        }
    }
    return best;
}

// ── _remainingRouteDistance (navigation.js:1327-1347) ────────────────────────
function _remainingRouteDistance(coords, lat, lon) {
    if (!coords || coords.length < 2) return null;
    const closest = _navFindClosestOnRoute(coords, lat, lon);
    if (!closest) return null;
    let remaining = _navHaversine(
        closest.snappedPoint.lat, closest.snappedPoint.lng,
        coords[closest.segmentIndex + 1].lat, coords[closest.segmentIndex + 1].lng
    );
    for (let i = closest.segmentIndex + 1; i < coords.length - 1; i++) {
        remaining += _navHaversine(
            coords[i].lat, coords[i].lng,
            coords[i + 1].lat, coords[i + 1].lng
        );
    }
    return { remainingDistanceMeters: remaining, routeOffsetMeters: closest.routeOffsetMeters };
}

// ── Dispatch table (normalises JS camelCase → Python snake_case for comparison) ──
const DISPATCH = {
    haversine: ({ lat1, lon1, lat2, lon2 }) =>
        _navHaversine(lat1, lon1, lat2, lon2),

    project_on_segment: ({ p, a, b }) => {
        const r = _navProjectOnSegment(p, a, b);
        return { point: r.point, t: r.t };
    },

    find_closest_on_route: ({ coords, lat, lon }) => {
        const r = _navFindClosestOnRoute(coords, lat, lon);
        if (!r) return null;
        return {
            snapped_point:       r.snappedPoint,
            segment_index:       r.segmentIndex,
            route_offset_meters: r.routeOffsetMeters,
        };
    },

    remaining_route_distance: ({ coords, lat, lon }) => {
        const r = _remainingRouteDistance(coords, lat, lon);
        if (!r) return null;
        return {
            remaining_distance_meters: r.remainingDistanceMeters,
            route_offset_meters:       r.routeOffsetMeters,
        };
    },
};

// ── stdin/stdout JSON interface ───────────────────────────────────────────────
let input = '';
process.stdin.on('data', chunk => { input += chunk; });
process.stdin.on('end', () => {
    try {
        const req = JSON.parse(input);
        const fn = DISPATCH[req.function];
        if (!fn) {
            process.stdout.write(JSON.stringify({ error: `Unknown function: ${req.function}` }) + '\n');
            process.exit(1);
        }
        const result = fn(req.args);
        process.stdout.write(JSON.stringify({ result }) + '\n');
    } catch (e) {
        process.stdout.write(JSON.stringify({ error: e.message }) + '\n');
        process.exit(1);
    }
});
