# OnHighGround2 — CLAUDE.md

This file provides context for Claude Code to assist development
without requiring repeated explanations.

-----

## Project Overview

OnHighGround2 is a **disaster escape navigation system**.

Unlike typical hazard maps that only show danger areas,
this system focuses on **guiding users to safe locations**.

Core concept:

```
danger → safe location → escape route
```

The system helps users make evacuation decisions during disasters.

-----

## Technology Stack

|Layer         |Technology                        |
|--------------|----------------------------------|
|Mapping       |OpenStreetMap (OSM)               |
|Elevation     |DEM (Digital Elevation Model)     |
|Routing       |OSRM (Open Source Routing Machine)|
|Backend       |Python / FastAPI                  |
|Frontend      |Web client (map UI)               |
|Infrastructure|Docker / Docker Compose           |

-----

## System Architecture

```
User device
↓
Web map UI
↓
Backend API (FastAPI)
↓
Routing engine (OSRM)
↓
Elevation + hazard analysis
```

### Main Components

**Frontend**

- Map display
- Hazard layer visualization
- Route display

**Backend**

- Route calculation API
- Elevation analysis
- Hazard data processing

**Data**

- DEM elevation data
- Hazard layers (tsunami, flood, storm surge, landslide)
- OSM road network

-----

## Hazard Layers

Hazard layers are **modular** — they can be enabled or disabled per region:

- `tsunami`
- `flood`
- `storm_surge`
- `landslide`

Each layer should be an independent data component.

-----

## Design Principles

1. **Action-oriented** — Guide evacuation actions, not just display information
1. **Minimal viable architecture** — Start simple, expand gradually
1. **Open ecosystem** — Prefer open-source software and open data
1. **Modular hazard layers** — Each hazard type is an independent module
1. **Offline resilience** — Work with limited connectivity where possible

-----

## Development Guidelines

**Prioritize:**

- Clear architecture
- Modular design
- Maintainability
- Practical implementation

**Avoid:**

- Unnecessary frameworks
- Enterprise-scale complexity
- Over-engineering

Focus on **incremental development**.

-----

## AI Assistance Scope

Claude Code may help with:

- Architecture design
- GIS data handling (DEM, OSM, hazard layers)
- FastAPI routing logic and endpoint design
- Hazard analysis algorithms
- Map UI design
- Documentation

-----

## Long-term Vision

```
local prototype
↓
open-source project
↓
global escape navigation platform
```

The goal is to support evacuation decisions in disaster-prone regions worldwide.

-----

## Author

Hideki / Brokendish  
Urban × Nature / Technology × Craft