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
- Tokyo data lake scaffold (`data_lake/registry`, `raw`, `normalized`, `validated`, `tiles`)

-----

## Hazard Layers

Hazard layers are **modular** — they can be enabled or disabled per region:

- `tsunami`
- `flood`
- `storm_surge`
- `landslide`

Each layer should be an independent data component.

Current implementation policy is Tokyo-first.
National roll-out is deferred until the ingestion and validation architecture is stable.

The current scaffold separates:

- source ingestion
- normalization
- validation
- derived outputs
- delivery artifacts

Do not assume a blank area is safe. Missing coverage and safe areas must remain distinct in data handling.

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

For hazard data work, prefer extending the new scripts layout:

- `scripts/download/`
- `scripts/normalize/`
- `scripts/validate/`
- `scripts/derive/`
- `scripts/tile_build/`
- `scripts/publish/`

The current minimal orchestrator is `scripts/run_tokyo_pipeline.sh`.

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
## UIパネルの初期化パターン（教訓）

state.js で直接代入している変数（navigationMode 等）は
起動時に setter を通らないため、
パネルの表示制御を setter に依存している場合は
初期化関数内で明示的に表示状態をセットする必要がある。

❌ state.js の直接代入に依存
✅ 初期化関数内で _lipUpdateNavMode(initMode) を同期的に呼ぶ
-----

# OnHighGround2 — AI作業ルール

## 重要
/live 関連の作業を始める前に必ず docs/live/DEVELOPMENT_GUARDRAILS.md を読むこと。

## 絶対に守る境界（詳細は上記ガードレール参照）
- 既存ナビ本体（index.html, navigation.js, nav-*.js, hazard-layers.js,
  location-info-panel.js, 既存ルート探索/reroute）は改変禁止
- live のコードは frontend/js/live/, backend/app/*/live_*.py 等、
  指定ディレクトリ内にのみ作成する
- backend / Martin / data_lake / shared 等の既存資源は「利用」はOK、「改変」はNG

## Author

Hideki / Brokendish  
Urban × Nature / Technology × Craft
