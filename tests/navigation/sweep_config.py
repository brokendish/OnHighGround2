"""
Sweep parameter ranges for navigation tuning tests.
Edit this file to adjust ranges before each field test iteration.
"""

# ── Sweep axes ───────────────────────────────────────────────────────────────

# arrival_radius candidates (metres) — centred on current default 40 m
ARRIVAL_RADIUS_SWEEP    = [15, 20, 25, 30, 35, 40, 45, 50, 60, 75]

# reroute_threshold candidates (metres) — centred on current default 30 m
REROUTE_THRESHOLD_SWEEP = [15, 20, 25, 30, 35, 40, 50, 75, 100]

# GPS noise levels (σ metres).  Urban typical: 5-15 m; canyon/indoor: 20-30 m
NOISE_SIGMA_SWEEP       = [0, 5, 10, 15, 20]

# Replications per (parameter, σ) cell — different seeds for each
NOISE_TRIALS    = 10
NOISE_SEED_BASE = 42        # reproducible; trial k uses seed NOISE_SEED_BASE + k

# ── Current defaults (navigation.js:12-37) ───────────────────────────────────
# Stored here for reference in reports; do NOT change these for tuning.

CURRENT_ARRIVAL_RADIUS    = 40   # NAV_ARRIVAL_M
CURRENT_REROUTE_THRESHOLD = 30   # NAV_REROUTE_THRESHOLD_M
CURRENT_OFF_ROUTE_M       = 20   # NAV_OFF_ROUTE_M
CURRENT_CONSECUTIVE       = 3    # NAV_CONSECUTIVE
CURRENT_DEBOUNCE_SEC      = 3.0  # NAV_OFF_ROUTE_DEBOUNCE_MS / 1000
CURRENT_MIN_DELTA_M       = 8    # NAV_MIN_DELTA_M

# Accuracy multiplier used in arrival effective-radius calculation
ACCURACY_MULTIPLIER       = 1.5  # navigation.js:1610  max(arrival_radius, accuracy * 1.5)

# GPS update interval assumed in tests (seconds) — matches nav watchPosition maximumAge
GPS_STEP_SEC  = 3.0
WALKING_SPEED = 1.3   # m/s  (average pedestrian)
