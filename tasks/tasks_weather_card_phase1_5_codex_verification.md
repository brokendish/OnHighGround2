# OnHighGround2 Weather Card Phase1.5 Codex Verification

## Verification Metadata

- Verification datetime: 2026-05-17 09:20 JST
- Branch: `main`
- Commit: `5ecdaeccdf14b008ae4c5c339a20f5eb715350d5`
- Scope:
  - `backend/services/jma_rain_tile_service.py`
  - `backend/app/services/weather_alert_service.py`
  - `backend/requirements.txt`
- Final judgment: **PASS with notes**

## Summary

Phase1.5 passes the Codex re-verification. Docker build succeeds with Pillow, backend starts, precipitation summary returns real intensity values instead of fixed `unknown`, 5x5 max sampling works for recognized rain colors, tile fetch failure does not crash the summary builder, and existing weather/rain/hazard APIs remain healthy.

The previous blocker was resolved: unrecognized opaque PNG colors now resolve to `unknown`, not `none`. `_sample_max_intensity()` now separates recognized rain, unknown opaque pixels, and recognized none pixels, preserving the intended priority `rain > unknown > none`.

## Docker / Dependencies

### Commands

```bash
docker compose build backend
docker compose up -d backend frontend martin osrm-walking
docker compose ps backend frontend martin osrm-walking
docker exec evacuation-navi-backend python -c "import PIL; print(PIL.__version__)"
```

### Results

- `docker compose build backend`: passed.
- Build installed `Pillow-11.3.0`, satisfying `Pillow>=10.0,<12`.
- `docker compose up -d backend frontend martin osrm-walking`: passed.
- `docker compose ps`:
  - backend: healthy
  - frontend: up
  - martin: healthy
  - osrm-walking: up
- Container Pillow version: `11.3.0`.

## API Checks

### Commands

```bash
curl -s 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125' | python3 -m json.tool
curl -i 'http://127.0.0.1:8000/api/weather/rain/tile/times'
curl -s 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125' | python3 -m json.tool
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### Results

- `/api/weather/precipitation/summary`: HTTP 200.
- Response included `current` and six forecast entries through +30 minutes.
- `intensity` was not fixed `unknown`; real result for Tokyo Station area was all `none`.
- Response:
  - `status: "ok"`
  - `severity: "none"`
  - `summary: "降水リスクなし"`
  - `current.intensity: "none"`
  - `forecast[].intensity: "none"`
- Existing rain tile API: HTTP 200.
- Weather alerts API: HTTP 200.
- Hazard active API: HTTP 200.

## Mock PNG Pixel Analysis

### Test Method

Ran in the rebuilt backend container with Pillow. `_lat_lon_to_tile_pixel()` was patched to return pixel `(10, 10)`, and `_fetch_tile_png()` was patched to return generated 32x32 PNGs.

### Results

| Case | Expected | Actual | Result |
|---|---:|---:|---|
| center pixel `strong` | `strong` | `strong` | PASS |
| `severe` within 5x5 window at `(12,12)` | `severe` | `severe` | PASS |
| `severe` just outside 5x5 window at `(13,10)` | `none` | `none` | PASS |
| all pixels `none` / white | `none` | `none` | PASS |
| center pixel unknown color `(123,123,123)` | `unknown` | `unknown` | PASS |
| all pixels unknown color `(123,123,123)` | `unknown` | `unknown` | PASS |
| mixed unknown + recognized `strong` | `strong` | `strong` | PASS |
| tile fetch failure | `unknown` | `unknown`, `source: fetch_failed` | PASS |

### Previously Blocking Issue

- File: `backend/services/jma_rain_tile_service.py`
- Function: `_sample_max_intensity()`
- Previous problem: unknown pixels had `rain_class=-1`, but the sample started as `none` with `rain_class=0`, so unknown colors never won.
- Re-verification result: fixed. The implementation now tracks `recognized_rain_found`, `unknown_opaque_found`, and `recognized_none_found` separately.
- Behavioral priority confirmed by mock PNGs: recognized rain wins first, unknown opaque colors win over none, and recognized none is returned only when no rain or unknown opaque pixel is present.
- Note: `recognized_none_found` is currently informational in the final return path, but this does not affect the verified behavior.

## Severity / Summary Logic

### Commands

```bash
PYTHONPATH=backend venv/bin/python -c "from app.services import weather_alert_service as w; ..."
```

### Results

- `strong` -> `warning`, `30分以内に強雨域が接近する可能性があります`
- `severe` -> `warning`
- `moderate` -> `advisory`, `30分以内に雨域が接近する可能性があります`
- `weak` -> `advisory`, `弱い雨が予測されています`
- `none` -> `none`, `降水リスクなし`
- `unknown` only -> `unknown`, `降水予測を判定できません`
- `unknown + strong` -> `warning`

This part matches the Phase1.5 intent: `unknown` is excluded from max severity when known stronger signals exist.

## Tile Failure Handling

Mocked `fetch_precip_intensities()` to raise `RuntimeError("tile fail")` inside `_build_precip_summary()`.

Result:

```text
status: ok
severity: unknown
summary: 降水予測を判定できません
current.intensity: unknown
forecast[].intensity: unknown
```

The API path does not crash when intensity analysis fails.

## E2E / Regression

### Commands

```bash
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
venv/bin/python -m pytest tests/test_weather_temperature.py -q
```

### Results

- `e2e/info-tab-card-ui.spec.js`: 3 passed.
- Existing weather temperature tests: 34 passed.
- Existing rain tile API, weather alerts API, and hazard active API remained HTTP 200.

## Notes For Calibration

- RGB to intensity table is approximate and needs calibration against actual JMA nowcast tiles.
- `zoom=8` may be enough for Phase1.5, but should be checked against real locations and near-boundary rain cells.
- 5x5 sampling is a good safety-oriented choice, but the physical footprint varies by zoom and latitude. It should be validated in rain-edge cases.
- Implementation analyzes at most seven time entries (`current + six forecasts through +30min`), but `fetch_precip_intensities()` uses `max_workers=4`. If “7 parallel” means seven concurrent workers, this is not currently true; if it means at most seven target tiles are analyzed concurrently through a pool, the structure is acceptable.

## Final Decision

**PASS with notes**

The build, APIs, E2E, recognized-color pixel analysis, unknown-color handling, 5x5 max sampling, and tile failure handling all pass. Remaining notes are calibration-oriented: RGB thresholds, `zoom=8`, and the 5x5 sampling footprint should be validated against real JMA tiles and field conditions.
