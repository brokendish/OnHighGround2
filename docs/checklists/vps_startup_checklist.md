# VPS Startup Checklist

Use this checklist when setting up the system on a new VPS, or after a full
container teardown. Follow the steps in order.

Tested environment: Debian 12, Docker 26+, 2 GB RAM VPS.

---

## 0. Prerequisites

- [ ] Docker and Docker Compose plugin installed (`docker compose version`)
- [ ] Git installed and repository cloned
- [ ] Port 8080 open in firewall (or 80/443 if behind a reverse proxy)

---

## 1. Directory Structure

The following directories must exist before starting containers.
They are **gitignored** and must be created manually on a fresh server.

```bash
mkdir -p data_lake/registry
mkdir -p data_lake/raw
mkdir -p data_lake/normalized
mkdir -p data_lake/validated
mkdir -p data_lake/tiles
mkdir -p data_runtime/backend/elevation
mkdir -p data_runtime/frontend/tiles
```

---

## 2. Hazard Data

Hazard data must be ingested via the admin UI (`/admin/datasets`) or pipeline
before the backend will serve hazard checks.

Minimum required for Tokyo coverage:

| Dataset | Notes |
|---|---|
| Tokyo tsunami | ~45 MB GeoJSON |
| Kanagawa tsunami | ~45 MB GeoJSON |
| Tokyo storm_surge | ~60 MB GeoJSON |
| Kanagawa storm_surge | ~60 MB GeoJSON |
| Tokyo landslide | ~100 MB GeoJSON |
| Kanagawa landslide | ~100 MB GeoJSON |
| Tokyo flood | ~80 MB GeoJSON |

Chiba tsunami is excluded by default on memory-constrained VPS.
See `backend/app.properties` → `hazard.tsunami.targets`.

See [Memory Tuning](../operations/vps_memory_tuning.md) for RAM requirements.

---

## 3. OSRM Walking Data

The OSRM walking index is built from a PBF file at first container start.
Place the PBF file before starting `osrm-walking`.

Expected path:
```
data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf
```

If this file is missing, the container will exit immediately (`test -f` fails).

**First-time build time**: 30–60 minutes on a 2 GB VPS.
**Do not stop the container during the build.**

To monitor build progress:
```bash
docker compose logs -f osrm-walking
```

Expected log sequence:
```
OSRM index not found — building from PBF...
[osrm-extract] ...
[osrm-partition] ...
[osrm-customize] ...
[info] Listening on: 0.0.0.0:5001
[info] running and waiting for requests
```

To rebuild the index (e.g. after a PBF update):
```bash
rm data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osrm*
docker compose restart osrm-walking
```

---

## 4. Starting Services

Start in this order to avoid dependency issues:

```bash
# Start backend and infrastructure first
docker compose up -d backend martin

# Wait for backend to be healthy (~30s)
docker compose ps

# Start frontend (nginx) — depends_on: backend, osrm-walking
# osrm-walking starts automatically as a dependency
docker compose up -d frontend
```

Or start everything at once (docker compose handles depends_on):
```bash
docker compose up -d
```

Note: `osrm-driving` does **not** start by default (profile-gated).

---

## 5. Health Checks

```bash
# All containers running (not Restarting)
docker compose ps

# Backend API
curl -s http://localhost:8000/health

# OSRM walking
curl -s "http://localhost:5501/route/v1/walking/139.69,35.68;139.70,35.69" | head -c 50

# Through nginx proxy (end-to-end)
curl -s "http://localhost:8080/api/health"
curl -s "http://localhost:8080/osrm/walking/route/v1/walking/139.69,35.68;139.70,35.69" | head -c 50
```

Expected: all return HTTP 200 with valid JSON.

---

## 6. Known Issues and Gotchas

### martin Restarting on startup

If Martin enters a Restarting loop, check `config/martin.yaml` for tile paths
that do not exist on disk. Comment out or remove entries for unbuilt datasets.

```bash
docker compose logs martin
```

### backend memory > 1.5 GB

- Check `backend/app.properties`: `hazard.tsunami.targets` should not include `chiba`
- All hazard loads in `backend/main.py` should use `bbox_only=True`
- See [Memory Tuning](../operations/vps_memory_tuning.md)

### osrm-walking shows help text and exits

If the container log shows `osrm-routed <base.osrm> [<options>]:` (the help
message), the OSRM index file is missing or the path is wrong.

Check:
```bash
ls data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/
```

The `.osrm` file and companion files (`.partition`, `.mldgr`, etc.) must all exist.

### nginx cannot proxy to osrm-walking

If `/osrm/walking/` returns `InvalidUrl` (HTTP 400), the nginx proxy is not
stripping the location prefix correctly. See
[nginx Proxy Patterns](../architecture/nginx_proxy_patterns.md).

The `proxy_pass` must use a **literal hostname with trailing slash**:
```nginx
proxy_pass http://osrm-walking:5001/;  # correct
```

### ShelterRegistry high CPU / memory churn

If the backend log shows shelter data being reloaded every 30 seconds,
check `backend/app/services/shelter_service.py`:

```python
_registry_instance = ShelterRegistry(ttl_seconds=3600)  # should be 3600, not 30
```

---

## 7. Verify End-to-End

Open `http://<your-vps-ip>:8080` in a browser.

- [ ] Map loads with shelter pins
- [ ] Hazard check returns results for a Tokyo location
- [ ] Evacuation route search completes and shows a walking route
