# AI Context — OnHighGround2

This file helps AI assistants understand the OnHighGround project.

The goal is to provide essential architectural context so that
AI tools (ChatGPT, Claude, Cursor, Copilot) can assist development
without requiring repeated explanations.

---

# Project Overview

OnHighGround is a disaster escape navigation system.

Unlike typical hazard maps that only show danger areas,
OnHighGround focuses on **guiding users to safe locations**.

Core concept:

danger  
↓  
safe location  
↓  
escape route

The system aims to help users make evacuation decisions during disasters.

---

# Project Goals

Primary goals:

1. Identify safer locations based on elevation and hazard data
2. Compute routes to those locations
3. Display evacuation guidance on a map
4. Work with open data and open-source software
5. Maintain a simple and extensible architecture

Future goal:

Develop an **Escape Navigation Engine** that can be reused globally.

---

# Core Technology Stack

Current stack:

Mapping
- OpenStreetMap (OSM)

Elevation
- DEM (Digital Elevation Model)

Routing
- OSRM (Open Source Routing Machine)

Backend
- Python / FastAPI

Frontend
- Web client (map UI)

Infrastructure
- Docker / Docker Compose

---

# System Architecture

Basic architecture:
User device
↓
Web map UI
↓
Backend API
↓
Routing engine (OSRM)
↓
Elevation + hazard analysis

Main components:

Frontend (`frontend/index.html`)

- Map display (Leaflet.js)
- Hazard layer visualization (tsunami / flood — MBTiles via Martin or GeoJSON fallback)
- Route display (Leaflet Routing Machine + OSRM)
- Evacuation result panel: danger status, recommended destination, candidate list

Backend (`backend/`)

- `main.py` — FastAPI server, all endpoints, shelter loading, search orchestration
- `elevation_service.py` — DEM loading, elevation lookup, grid-based candidate search (fallback)
- `hazard_service.py` — Multi-hazard polygon loading (GeoJSON), point-in-polygon判定（Ray casting）
  - `assess_candidate(lat, lon) -> Dict[str, HazardResult]` — returns per-hazard results for all loaded types
  - `derive_hazard_safe(assessment) -> Optional[bool]` — any inside→False, all outside→True, unknown→None
  - `HazardResult = Literal["inside", "outside", "unknown"]`

Data (`data_lake/`)

- DEM: `validated/tokyo/dem/elevation.tif`
- Shelter: `normalized/tokyo/shelter/tokyo_shelter.geojson`
- Flood hazard: `normalized/tokyo/flood/tokyo_flood_max.geojson`（925,958 polygons, A31a + A31b 統合）
- Tsunami hazard: `normalized/tokyo/tsunami/*.geojson`
- MBTiles（frontend tile delivery）: `tiles/tokyo/`

---

# Design Principles

1. Action-oriented design  
   The system should guide evacuation actions, not just display information.

2. Minimal viable architecture  
   Start simple and expand gradually.

3. Open ecosystem  
   Prefer open-source software and open data.

4. Modular hazard layers  
   Hazard types (tsunami, flood, landslide) should be modular.

5. Offline resilience  
   The system should work even with limited connectivity where possible.

---

# Hazard Layers

Hazard layers may include:

- tsunami
- flood
- storm surge
- landslide

These layers should be designed as modular data components
that can be enabled or disabled depending on the region.

Current implementation direction:

- Tokyo-first
- data-lake based ingestion pipeline
- clear separation between raw, normalized, validated, and delivery artifacts
- avoid treating missing hazard coverage as safe

Currently active in backend hazard assessment:

- **flood** — `data_lake/normalized/tokyo/flood/tokyo_flood_max.geojson` (925,958 polygons, A31a + A31b)
- **tsunami** — `data_lake/normalized/tokyo/tsunami/tokyo_tsunami_A40-23_13.geojson` (Tokyo default)
  - Configurable via `hazard.tsunami.targets=tokyo` (CSV; extend to kanagawa, chiba for wide-area mode)
- **storm_surge** — `data_lake/normalized/tokyo/storm_surge/tokyo_storm_surge.geojson`
- **inland_flood** — GeoJSON polygon check + Severity display (Phase 4)
- **landslide** — GeoJSON polygon check + Severity display (Phase 4)

The current scaffold introduces:

- `data_lake/registry/` for registry metadata
- `data_lake/raw/` for original source data
- `data_lake/normalized/` for standardization outputs
- `data_lake/validated/` for validation-passed outputs
- `data_lake/tiles/` for delivery artifacts

The first end-to-end pipeline is intentionally minimal:

`registry check -> shelter ingest -> shelter normalize -> geometry validate`

---

# AI Development Guidance

AI assistants should prioritize:

- clear architecture
- modular design
- maintainability
- practical implementation

Avoid:

- unnecessary frameworks
- enterprise-scale complexity
- over-engineering

Focus on incremental development.

---

# Expected AI Assistance

AI tools may help with:

- architecture design
- GIS data handling
- routing logic
- hazard analysis
- UI design
- documentation

---

# Long-term Vision

OnHighGround aims to evolve from a local experiment into a reusable system.

Potential evolution:

local prototype  
↓  
open-source project  
↓  
global escape navigation platform

The long-term vision is to support evacuation decisions
in disaster-prone regions worldwide.

---

# Author

Hideki  
Brokendish

Urban × Nature  
Technology × Craft
