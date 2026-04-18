# VPS Memory Tuning — Backend

## Background

The backend was consuming **~4.7 GiB** of RAM on a 1.9 GiB VPS, causing OOM kills
and container instability. This document records what was causing the bloat,
what was changed, and how to reconfigure if memory constraints change.

---

## Root Causes

### 1. HazardService: full coordinate arrays in memory

`hazard_service.py` loaded all GeoJSON polygons as full coordinate rings.
Python's in-memory representation of parsed JSON is 3–8× the raw file size,
so a 100 MB GeoJSON file could consume ~500 MB of heap.

Affected datasets and their approximate raw sizes:

| Layer | Files | Raw size |
|---|---|---|
| tsunami (tokyo + kanagawa) | 2 | ~90 MB |
| storm_surge (tokyo + kanagawa) | 2 | ~120 MB |
| landslide (tokyo + kanagawa) | 2 | ~200 MB |

### 2. ShelterRegistry TTL = 30s

`shelter_service.py` was set to `ttl_seconds=30`, which matched the Docker
healthcheck interval. The result was a continuous reload loop where the entire
shelter dataset was re-read from disk every 30 seconds.

### 3. Chiba tsunami dataset loaded by default

The chiba tsunami GeoJSON (~139 MB) was included in the default load targets.
On a memory-constrained VPS it is unnecessary as coverage does not reach chiba.

---

## Fixes Applied

### bbox_only mode in HazardService (`backend/hazard_service.py`)

`HazardService.load()` accepts `bbox_only=True`. In this mode, instead of
storing full polygon coordinates, only the minimum bounding box (bbox) is kept:

| Layer | What is stored in bbox_only mode |
|---|---|
| tsunami | `{bbox, centroid}` — centroid is precomputed for distance queries |
| storm_surge | `{bbox}` — only used for containment check |
| landslide | `{bbox, properties}` — properties needed for detail display |
| flood | `{bbox, coords}` — full coords retained (flood still uses polygon intersection) |

Calls in `backend/main.py` at startup:

```python
# storm_surge
hazard_service.load("storm_surge", path, bbox_only=True)

# tsunami
hazard_service.load("tsunami", path, bbox_only=True)

# landslide
hazard_service.load("landslide", path, bbox_only=True)
```

**Trade-off**: point-in-polygon accuracy is reduced to bbox hit for storm_surge
and landslide. For tsunami, centroid distance is preserved. This is acceptable
for the primary use case (evacuation routing), but should be revisited if
precision hazard analysis is needed.

### ShelterRegistry TTL (`backend/app/services/shelter_service.py`)

```python
# Before (caused constant reload every 30s)
_registry_instance = ShelterRegistry(ttl_seconds=30)

# After
_registry_instance = ShelterRegistry(ttl_seconds=3600)
```

To force a reload (e.g. after deploying new shelter data):

```bash
docker compose restart backend
```

### Chiba tsunami excluded (`backend/app.properties`)

```properties
# chiba excluded on VPS (139 MB, ~1 GB in-memory; coverage not needed)
hazard.tsunami.targets=tokyo,kanagawa
```

To re-enable chiba (if moving to a higher-memory host):

```properties
hazard.tsunami.targets=tokyo,kanagawa,chiba
```

**Note**: Disabling chiba means users in the chiba coastal area will not receive
a tsunami warning. Do not re-enable without ensuring the VPS has enough RAM,
and do not disable without noting this in release notes.

---

## Result

| Before | After |
|---|---|
| ~4.7 GiB | ~2.5 GiB |

Tested on a 1.9 GiB VPS (ConoHa VPS 2 GB plan). Stable with ~400 MB headroom
for OS and other services.

---

## Future Work

- Streaming GeoJSON parser (GeoJSONL / ijson) to avoid peak load at startup
- Tile-server delivery (Martin) for hazard layers instead of in-memory polygons
- Per-region feature flags so individual datasets can be excluded without code changes
