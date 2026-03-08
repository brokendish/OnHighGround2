# scripts/ — Tile Generation Pipeline

This directory contains scripts for converting hazard GeoJSON data into
vector tiles.

---

## Prerequisites

### Install tippecanoe

**macOS (Homebrew):**
```bash
brew install tippecanoe
```

**Ubuntu / Debian:**
```bash
sudo apt install tippecanoe
```

**Build from source:**
```
https://github.com/felt/tippecanoe
```

Verify installation:
```bash
tippecanoe --version
```

---

## build_tiles.py

Converts all `.geojson` files found in the input directory into
`.mbtiles` vector tile files using tippecanoe.

### Basic usage

```bash
python scripts/build_tiles.py
```

This reads GeoJSON files from `data/processed/hazard/` (the canonical
source location) and outputs `.mbtiles` files to `tiles/`.

### Options

| Option | Default | Description |
|--------|---------|-------------|
| `--minzoom` | 5 | Minimum zoom level |
| `--maxzoom` | 14 | Maximum zoom level |
| `--input DIR` | `data/processed/hazard` | Directory containing GeoJSON files |
| `--output DIR` | `tiles` | Output directory for .mbtiles files |
| `--dry-run` | — | Print commands without executing |

### Examples

```bash
# Default run (reads from data/processed/hazard/)
python scripts/build_tiles.py

# Custom zoom range
python scripts/build_tiles.py --minzoom 8 --maxzoom 16

# Temporary: use frontend/hazard/ as input (legacy location)
python scripts/build_tiles.py --input frontend/hazard

# Preview without executing
python scripts/build_tiles.py --dry-run
```

---

## Current directory structure

```
data/
  hazard/                  ← Raw source data (GML, Shapefile) — do not edit
    A40-16-14/
    A40-18-12/
    ...
  processed/
    hazard/                ← Canonical GeoJSON location (input for tile generation)
      tsunami_tokyo.geojson
      tsunami_kanagawa.geojson
      tsunami_chiba.geojson

frontend/hazard/           ← LEGACY / TEMPORARY: GeoJSON copies used by the current frontend
                             Do NOT treat this as the long-term source location.
                             Files here can still be used via --input frontend/hazard.

tiles/                     ← Generated .mbtiles output (gitignored)
  tsunami_tokyo.mbtiles
  tsunami_kanagawa.mbtiles
  tsunami_chiba.mbtiles

scripts/
  build_tiles.py           ← This script
  README.md                ← This file
```

> **Note:** `data/` is gitignored in this repository. Files under
> `data/processed/hazard/` exist only locally and must be generated or
> copied manually. This is intentional — hazard GeoJSON files are large
> and are derived from the raw source data under `data/hazard/`.

---

## Adding a new hazard dataset

1. Place the processed GeoJSON file into `data/processed/hazard/`:

   ```
   data/processed/hazard/flood_tokyo.geojson
   ```

2. Run the tile generation script:

   ```bash
   python scripts/build_tiles.py
   ```

   The script automatically discovers all `.geojson` files in the input
   directory. No code changes are needed.

### Temporary: using frontend/hazard/ as input

Until GeoJSON files have been migrated to `data/processed/hazard/`, you
can use the legacy location:

```bash
python scripts/build_tiles.py --input frontend/hazard
```

`frontend/hazard/` is kept for frontend rendering compatibility but
**should not be the canonical storage location** for hazard GeoJSON source
data going forward.

---

## Intended future directory structure

As the project expands to cover more regions and hazard types, the
recommended long-term layout is:

```
data/
  raw/                     ← Original source data (GML, Shapefile, etc.)
  processed/               ← Cleaned and normalized GeoJSON

tiles/
  japan/
    tokyo/
      tsunami/
        tsunami_tokyo.mbtiles
      flood/
        flood_tokyo.mbtiles
    kanagawa/
      tsunami/
        tsunami_kanagawa.mbtiles

scripts/
  build_tiles.py           ← Tile generation (update --input/--output paths)
```

The current flat layout (`tiles/{dataset}.mbtiles`) is intentional for
simplicity at this stage. Migration to the region-aware layout can be done
incrementally when the number of datasets grows.

---

## Assumptions and limitations

- tippecanoe must be installed locally (not included in Docker setup).
- GeoJSON files are assumed to use EPSG:4326 (WGS84), which is standard
  for Japanese government hazard datasets.
- The `.mbtiles` format is suitable for local use and testing.
  For production tile serving, consider converting to
  [PMTiles](https://protomaps.com/docs/pmtiles) or serving via a tile
  server such as [Martin](https://github.com/maplibre/martin).
