# Navigation Field Test Protocol

**Purpose:** Validate simulation predictions against real GPS behavior.
**Estimated time:** 30-45 min per session.

---

## Pre-test checklist

- [ ] Browser DevTools Console open (or remote debug via USB)
- [ ] `[NAV]` logs confirmed visible (look for `[NAV] dist_to_dest=` on movement)
- [ ] Destination set to a landmark with known coordinates
- [ ] Route confirmed loaded (blue line visible on map)
- [ ] Log capture tool ready (see "Log capture" section below)

---

## Observation items

### 1. GPS accuracy distribution

Record GPS `accuracy` value on every position update during a walk.

**Target:** Collect ≥ 60 samples in normal urban conditions.

**Log line:** `[NAV] dist_to_dest=XX.Xm, accuracy=XX.Xm, radius=XX.Xm`

**What to compute post-test:**
- Median accuracy
- 95th-percentile accuracy
- Fraction of samples where `accuracy > 50m` (low-accuracy threshold)

**Simulation assumption:** σ = 10-15m covers typical urban GPS.
Verify median accuracy aligns with this range.

---

### 2. Arrival detection effective radius

Walk directly toward destination and pass through it.

**Record:**
- `dist_to_dest` value at the moment `✅ ARRIVAL DETECTED` log appears
- GPS `accuracy` at that moment
- `effectiveRadius = max(40m, accuracy × 1.5)`

**Expected:** `dist_to_dest ≤ effectiveRadius` at trigger point.

**Current default:** `arrival_radius = 40m`
→ If GPS accuracy ≤ 27m, effective radius = 40m.
→ If GPS accuracy > 27m, effective radius = accuracy × 1.5.

---

### 3. Reroute effective delay

Walk on-route, then deliberately deviate ≥ 50m perpendicular to route and hold position.

**Record:**
- Timestamp of first step off-route (when `off_route=` value exceeds threshold)
- Timestamp of `🔄 AUTO REROUTE TRIGGERED` log
- Difference = observed reroute delay

**Simulation prediction:** ~12s minimum (3 consecutive × 3s GPS interval + 3s debounce).

**Note:** Actual delay may be longer due to:
- GPS update interval variations
- Debounce reset on brief on-route readings

---

### 4. GPS loss duration

Walk through tunnel, underpass, or tall building canyon.

**Record:**
- Duration with no position updates (gap between consecutive `[NAV]` log lines)
- Whether reroute incorrectly fired during or after GPS loss recovery

**Threshold:** Loss > 30s may cause stale position issues.

---

### 5. Reroute false fire near destination

Walk toward destination but approach from an angle ≥ 30m offset from route endpoint.

**Record:**
- Whether reroute fired before arrival
- `dist_to_dest` value when reroute fired (if it did)

**Expected (post-fix):** Arrival fires first; no reroute within effective arrival radius.
**Watch for:** `reroute_triggered` log before `ARRIVAL DETECTED`.

---

## Log capture

### Method A — Browser console copy
1. Open DevTools → Console
2. Filter by `[NAV]`
3. Right-click → "Save as" or copy all

### Method B — Remote debug (Android)
```
chrome://inspect → Select device → Console
```

### Method C — iOS Safari
```
Safari → Develop → [device name] → Console
```

### Paste format for post-analysis
Save raw console output as `data/test_fixtures/gps_traces/field_tests/<date>_<location>.txt`

---

## Post-test routine

1. Save raw log file with naming: `YYYYMMDD_locationname.txt`
2. Run `grep "\[NAV\]" <logfile>` to extract navigation lines
3. Parse accuracy values: `grep "accuracy=" | sed 's/.*accuracy=\([0-9.]*\).*/\1/'`
4. Compare median accuracy to simulation σ assumption
5. Record reroute delay and compare to ~12s prediction
6. If observed median accuracy > 20m, re-run simulation sweep with σ=20m as baseline

---

## Decision criteria

| Observation | Action |
|---|---|
| Median accuracy ≤ 15m | Current parameters safe per simulation |
| Median accuracy 15-25m | Monitor; σ=20m sweep row shows arrival still 100% |
| Reroute fires near destination | Check `reroute_threshold` vs arrival radius; consider raising threshold to 50m |
| Reroute delay >> 12s | Check GPS update interval; may need to reduce `NAV_CONSECUTIVE` |
| Reroute fires on-route (false positive) | Raise `reroute_threshold`; current 30m unsafe at σ≥15m |

---

## Parameter change candidates (from simulation)

| Issue | Current | Recommended | Basis |
|---|---|---|---|
| On-route false fire (σ≥15m) | `reroute_threshold=30m` | `50m` | Only threshold passing dual criteria |
| Arrival radius | `arrival_radius=40m` | Keep | All radii 15-75m are safe |

*See `reports/parameter_sweep/RECOMMENDATION.md` for full analysis.*
