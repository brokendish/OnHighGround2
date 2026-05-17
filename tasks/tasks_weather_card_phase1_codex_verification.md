# OnHighGround2 Weather Card Phase1 Codex Verification

## Verification Metadata

- Verification datetime: 2026-05-17 01:05 JST
- Re-verification datetime: 2026-05-17 01:23 JST
- Branch: `main`
- Commit: `5ecdaeccdf14b008ae4c5c339a20f5eb715350d5`
- Scope: JMA weather alert adapter, precipitation summary API, information tab weather card, map weather banner
- Final judgment: **PASS with notes**

## Static Review

### Passed

- Backend separates new alert/precipitation flow into:
  - `backend/app/api/weather.py`
  - `backend/app/services/weather_alert_service.py`
  - `backend/app/services/jma_weather_adapter.py`
  - `backend/app/models/weather_alert.py`
- Frontend does not read JMA raw XML/JSON directly. It consumes normalized API responses through:
  - `frontend/js/weather-service.js`
  - `frontend/js/weather-card.js`
  - `frontend/js/weather-alert-ui.js`
- `severity` is normalized to `none | advisory | warning | emergency | unknown`.
- `intensity` shape is normalized in the precipitation API response, although Phase1 returns `unknown` for actual intensities.
- Unknown alert kinds are retained as `severity: "unknown"` instead of crashing.
- AMeDAS temperature UI is not re-enabled. `frontend/js/weather.js` remains not loaded from `frontend/index.html`.

### Re-verified Fixes

- `reverse_geocode_service.py` now returns `city` from `_build_response()` in all checked paths, including disabled/cache/provider/fallback paths.
- `jma_weather_adapter.py` now loads `pref_centroids` and `area_city_keywords` from `data_runtime/backend/weather/jma_area_codes.json`, with `data_lake/registry/weather/jma_area_codes.json` fallback.
- `filter_alerts_for_city()` filters alert items by current city to the matching JMA primary area label, with full-list fallback when no match exists.
- `weather_alert_service.py` now resolves city through reverse geocode and includes it in `location.city`.
- Weather alert persistent cache now writes to `data_runtime/backend/weather/cache/alerts_{pref_code}.json`.
- Container path check confirmed runtime paths resolve to `/data_runtime/backend/weather/...`, not an accidental `/app/data_runtime/...`.
- `frontend/js/weather-alert-ui.js` now clears the map banner for `status: "unavailable"` and `severity: "none"`.
- `e2e/info-tab-card-ui.spec.js` now expects `気象` instead of the old `気象（将来予報）`.

### Remaining Notes

- Prefecture selection still uses nearest prefecture centroid. City-level filtering reduces false positives within the fetched prefecture, but prefecture resolution near borders is still approximate.
- `filter_alerts_for_city()` intentionally falls back to all prefecture items when the city is unknown or unmapped. This matches the provided Claude summary, but it can still show broader alerts if mapping coverage is incomplete.
- The adapter still assumes the current JMA warning JSON has top-level `areaTypes`; deeper field-name fallback exists inside each area. Future 2026 schema changes may still require adapter updates.

## Backend API Results

### Commands

```bash
docker compose restart backend
curl -s http://127.0.0.1:8000/health
curl -i 'http://127.0.0.1:8000/api/weather/alerts/current?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/precipitation/summary?lat=35.681236&lon=139.767125'
curl -i 'http://127.0.0.1:8000/api/weather/rain/tile/times'
curl -i 'http://127.0.0.1:8000/api/hazards/active'
```

### Results

- Before backend restart, the new weather endpoints returned `404 Not Found`. The compose backend uses a bind mount but uvicorn is not running with auto-reload.
- After `docker compose restart backend`, both new endpoints returned HTTP 200.
- Re-run after Claude fixes: `/api/weather/alerts/current?lat=35.681236&lon=139.767125` returned:
  - `status: "ok"`
  - `severity: "none"`
  - `alerts: []`
  - `location.area_name: "東京都"`
  - `location.pref_code: "130000"`
  - `location.city: "千代田区"`
- Re-run after Claude fixes: `/api/weather/precipitation/summary?lat=35.681236&lon=139.767125` returned:
  - `status: "ok"`
  - `severity: "none"`
  - `summary: "降水ナウキャスト取得済み（観測+予測 最大55分先）"`
  - `current.intensity: "unknown"`
  - forecast entries through +30 minutes with `intensity: "unknown"`
- Existing rain tile API still returned HTTP 200.
- Existing hazard active API still returned HTTP 200.

## Error Handling / Mock Checks

### Commands

```bash
PYTHONPATH=backend venv/bin/python -c "..."
```

### Results

- Unknown alert code/name mock produced one item with `severity: "unknown"` and did not crash.
- JMA fetch failure with no cache returned `status: "unavailable"` and did not crash.
- JMA fetch failure with stale in-memory cache returned `status: "stale"`.
- City filtering mock:
  - `千代田区` kept only `東京地方`.
  - `大島町` kept only `伊豆諸島北部`.
  - unknown city fell back to all items.
- Persistent cache mock:
  - Successful fetch wrote `alerts_130000.json`.
  - Subsequent simulated fetch failure with empty memory cache returned `status: "stale"` and restored the warning from persistent cache.

## Frontend UI Results

### Commands

```bash
npx playwright test e2e/info-tab-card-ui.spec.js --reporter=line
node -e "const { chromium } = require('@playwright/test'); ..."
```

### Results

- Existing `e2e/info-tab-card-ui.spec.js`: **3 passed**.
- Direct Playwright mock check:
  - `severity: none`: card showed `警報・注意報なし` and `降水リスクなし`; map banner display was `none`.
  - `severity: warning` with `大雨警報`: card showed warning state; map banner display was `flex` and contained `大雨警報 発表中`.
  - `status: unavailable` after a previous warning: card showed `気象情報を取得できません`; map banner display changed to `none`.

## Regression Results

- Docker services after restart:
  - backend: healthy
  - frontend: up
  - martin: healthy
  - osrm-walking: up
- Existing rain layer API remained available.
- Existing hazard API remained available.
- Existing AMeDAS temperature unit tests passed:

```text
34 passed in 0.04s
```

## Blocking Issues

- None remaining from the previous FAIL set.

## Final Decision

**PASS with notes**

The previous blockers were rechecked and are now resolved in implementation and runtime behavior: new APIs return HTTP 200, city-aware filtering is integrated, area mapping is externalized, persistent cache fallback works, the information tab E2E passes, and the map banner clears when weather data becomes unavailable. Remaining notes are about approximation and future JMA schema resilience rather than current Phase1 blockers.
