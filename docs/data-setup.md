# Data setup

This is the canonical data-preparation guide. Start with
[Installation](installation.md) for host prerequisites and the public-core
smoke path. Large source data and generated artifacts are intentionally not
committed to Git.

## Data flow and directories

```text
data_lake/raw/<region>/        downloaded or manually imported source data
data_lake/normalized/<region>/ normalized GeoJSON/GeoJSONL and derived data
data_lake/validated/<region>/  validated DEM, shelters, and OSRM inputs
data_lake/tiles/<region>/      generated MBTiles for Martin
data_runtime/current/          atomically published runtime version
```

`data_runtime/current/` is the runtime source. Do not copy data directly into
it. `scripts/publish/deploy_to_runtime.sh --dry-run` previews the mapping;
actual publishing uses `scripts/publish/deploy_to_runtime_atomic.sh --region
tokyo` from the privileged operator workflow. The direct non-dry-run publish
script fails closed without its staging environment.

## Core datasets

| Dataset | Classification | Acquisition/preparation | Required output / consumer | Freshness |
| --- | --- | --- | --- | --- |
| Driving OSM PBF | core for driving OSRM | Geofabrik through `scripts/download/download_osm.sh kanto`; copy/preprocess into the exact validated path below | `data_lake/validated/tokyo/osm/driving/kanto-260214.osm.pbf`; `osrm-driving` | periodically updated |
| Walking OSM PBF | core for walking routing | Geofabrik source; prepare the walking extract for the exact path below | `data_lake/validated/tokyo/osm/walking/tokyo-kanagawa/tokyo-kanagawa-260214.osm.pbf`; `osrm-walking` | periodically updated |
| DEM | core for elevation-aware results | Obtain GSI numerical elevation data and convert/validate with the project data process | `data_lake/validated/tokyo/dem/elevation.tif`; backend after publish | static source, refresh as needed |
| Flood hazard | core for configured flood checks | Manually obtain KSJ A31 ZIP, then use `scripts/download/download_river_flood.sh` and normalization/filtering | `data_lake/normalized/tokyo/flood/tokyo_flood_check.geojsonl`; backend after publish | periodically updated |
| Shelters | core for shelter results | GSI GeoJSON through `scripts/download/download_emergency_shelter.sh` or `download_shelter.sh`, then normalize/validate | `data_lake/validated/tokyo/shelter/*.geojson` or `.csv`; backend after publish | periodically updated |

The OSM downloader supports `kanto` and `japan` source regions (`--list-regions`
shows the URLs). It writes a PBF and a manifest under the requested output path.
The Compose file uses fixed versioned filenames above; ensure the prepared input
is placed at those exact paths before starting OSRM.

### OSRM preprocessing

The Compose services use MLD preprocessing:

```text
PBF → osrm-extract → osrm-partition → osrm-customize → .osrm* artifacts
```

`osrm-driving` uses `/opt/car.lua` and the `kanto-260214` prefix. `osrm-walking`
uses `osrm/foot.lua` and the `tokyo-kanagawa-260214` prefix. Their service
commands generate the artifacts in the corresponding validated directories if
they are absent. Preprocessing can use substantial CPU, memory, disk, and time;
no exact host minimum has been established. Verify that the PBF exists and that
the expected `.osrm`, `.osrm.partition`, `.osrm.mldgr`, `.osrm.cells`,
`.osrm.fileIndex`, and `.osrm.ramIndex` files are non-empty before relying on a
routing service.

### DEM

The backend expects the published file at
`data_runtime/current/backend/elevation/elevation.tif` (mounted as
`/data_runtime/backend/elevation/elevation.tif`). The publish input is
`data_lake/validated/tokyo/dem/elevation.tif`. DEM source attribution is
[GSI](https://www.gsi.go.jp/kikakuchousei/kikakuchousei40182.html); see
[ATTRIBUTIONS.md](../ATTRIBUTIONS.md).

### Flood and other hazards

KSJ flood A31 distribution is a manual-download flow because the project does
not have a confirmed stable direct-download URL. Download the ZIP from the
[official A31 page](https://nlftp.mlit.go.jp/ksj/gml/datalist/KsjTmplt-A31.html),
then run:

```bash
scripts/download/download_river_flood.sh /path/to/A31.zip 13
```

The script validates and imports source data to `data_lake/raw/tokyo/flood` by
default. Run the repository's flood normalization/filtering workflow to create
the `tokyo_flood_check.geojsonl` runtime input. Tsunami, storm-surge,
inland-flood, landslide, and lowland-drainage paths are consumed from the
normalized/validated layout by `scripts/publish/deploy_to_runtime.sh`. The
configured tsunami targets are `tokyo,kanagawa`; missing target data produces
an unavailable/unknown capability rather than a claim of safety.

## Tiles and Martin

Martin is a containerized MBTiles server; no PostGIS service, external database
connection, schema, migration, or seed command is declared in the current
Compose configuration. Martin reads `data_runtime/current/frontend/tiles` as
`/tiles` and `config/martin.yaml` declares the MBTiles directories it scans.
Generate or supply `.mbtiles` under `data_lake/tiles/<region>/<hazard>/`, then
publish atomically. Missing directories cause Martin to continue with a warning;
the corresponding layer is unavailable.

## Runtime API data and optional services

JMA, Open-Meteo, JARTIC, and ODPT are runtime services, not install-time
datasets. ODPT needs `ODPT_API_KEY` for its optional railway-information feature.
JARTIC and road-traffic settings are optional; see [Configuration](configuration.md).
These responses are not committed to the repository. Streamer data/configuration
is optional and separately secret-bearing.

## Publish and validate

1. Preview mappings: `scripts/publish/deploy_to_runtime.sh --region tokyo --dry-run`.
2. In the authorized operator workflow, publish atomically:
   `scripts/publish/deploy_to_runtime_atomic.sh --region tokyo`.
3. Confirm `data_runtime/current/` resolves and contains the expected runtime
   files; inspect the generated manifest under `data_runtime/manifests/`.
4. Start only the services whose inputs exist. Missing walking/driving PBFs make
   the respective OSRM service fail its file check; absent backend datasets lead
   to degraded/unknown results.

## Attribution and update policy

Keep provider terms, source URL, fetch time, and hashes produced by download
scripts. OSM attribution is © OpenStreetMap contributors under ODbL; GSI and
KSJ attribution/terms are listed in [ATTRIBUTIONS.md](../ATTRIBUTIONS.md).
Review provider terms before each periodic source refresh. Never commit raw
large datasets, generated OSRM artifacts, runtime versions, or downloaded API
responses unless their licensing and release classification are explicitly
reviewed.
