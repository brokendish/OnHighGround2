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