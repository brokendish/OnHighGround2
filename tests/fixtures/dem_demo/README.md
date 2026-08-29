# dem_demo — synthetic DEM fixture (AT-17A demo profile only)

This directory holds a minimal, fully synthetic Digital Elevation Model
(DEM) fixture used only by the `docker-compose.demo.yml` AT-17A demo/smoke
profile. It exists so `backend/elevation_service.py` can load a DEM through
its real, unmodified loader path and `GET /api/stats` can return `200`
during the demo profile's independent verification — without shipping any
real elevation data or touching the production DEM pipeline.

**This is not real elevation data.** Values come from an explicit
mathematical formula in `generate_synthetic_dem.py` (see `MANIFEST.json`
`elevation_formula`), not from any survey, satellite, or GSI dataset. Do
not use this fixture to inform real evacuation, hazard, or elevation
decisions.

## Files

- `elevation_demo.tif` — the generated single-band float32 GeoTIFF (CRS
  `EPSG:6668`, same axis-swap layout as the real production DEM).
- `generate_synthetic_dem.py` — deterministic generator (Python + rasterio
  only, no network, no RNG). Running it twice on the same rasterio/GDAL
  version produces a byte-identical file.
- `MANIFEST.json` — full provenance: generator command/hash, file hash,
  CRS, bbox, grid size, nodata contract, and expected statistics.

## Regenerating

```bash
python3 tests/fixtures/dem_demo/generate_synthetic_dem.py \
    --output tests/fixtures/dem_demo/elevation_demo.tif
```

## Coverage

The fixture bbox covers the `tests/fixtures/osm_demo/` demo OSM extract's
bounding box (Tokyo Station vicinity) with a 0.02° margin on every side,
so any point inside the demo OSM area has valid interpolation neighbors.
A small 3×3 cell block near the fixture's corner (away from the demo OSM
bbox interior) is deliberately set to the `-9999.0` NoData sentinel to
exercise `ElevationService`'s NoData contract without affecting the demo
area itself.

## Mount point

`docker-compose.demo.yml` mounts `elevation_demo.tif` read-only directly at
the path `backend/elevation_service.py`'s existing default configuration
(`dem.path` in `backend/app.properties`) already expects
(`/data_runtime/backend/elevation/elevation.tif` inside the container). No
application code, `DEM_FILE_PATH`-style environment variable, or
`app.properties` change was needed — the fixture simply supplies the file
at the path the loader was already going to look for.
