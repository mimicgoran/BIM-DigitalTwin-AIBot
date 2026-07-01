# GridTwin

A spatial data pipeline that integrates open geospatial datasets, building energy modelling, and a domain-constrained AI assistant to support infrastructure monitoring and analysis at the urban scale.

The methodology is designed to be transferable. What works for mapping energy performance across a city block works equally well for asset condition monitoring across a distribution network, substation footprint analysis, or demand forecasting tied to real spatial context. The dataset here is a residential neighbourhood in Belgrade, Serbia. The pipeline is the point.

---

## Table of Contents

- [What This Demonstrates](#what-this-demonstrates)
- [Live Demo](#live-demo)
- [System Architecture](#system-architecture)
- [Data Sources](#data-sources)
- [Methodology](#methodology)
- [Potential Applications](#potential-applications)
- [Project Structure](#project-structure)
- [Installation & Local Setup](#installation--local-setup)
- [Deployment](#deployment)
- [Known Limitations](#known-limitations)
- [Technology Stack](#technology-stack)
- [Data Disclaimer](#data-disclaimer)

---

## What This Demonstrates

- Automated ingestion and processing of open geospatial data (OSM PBF, GHSL raster) into analysis-ready GeoJSON
- Per-asset attribute enrichment: floor count, height, gross area, construction epoch, simulated energy intensity
- Raster-to-vector spatial join between a 100 m resolution EU satellite dataset and 8,300+ individual building polygons
- Real-time meteorological data feed integrated at the asset (park/zone) level via Open-Meteo API
- 3D interactive visualisation with energy classification colour scheme and click-through attribute inspection
- Domain-constrained AI assistant with structured spatial context, strict anti-hallucination guardrails, and bilingual output (Serbian / English)
- Full deployment on free-tier infrastructure: GitHub Pages (frontend) and Render.com (Flask API backend)

The stack is deliberately lean. No proprietary GIS platform, no paid data subscription, no cloud compute. The goal is to show what the methodology can do, not what the budget can buy.

---

## Live Demo

- **Application:** https://mimicgoran.github.io/BIM-DigitalTwin-AIBot/frontend/index.html
- **Backend health check:** https://bim-digitaltwin-aibot.onrender.com/api/health

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                          USER                               │
│                  Browser / Mobile Device                    │
└────────────────────────────┬────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                 FRONTEND (GitHub Pages)                     │
│                  frontend/index.html                        │
│                                                             │
│  ┌──────────────────┐    ┌─────────────────────────────┐   │
│  │  MapLibre GL JS  │    │        AI Chat UI            │   │
│  │  3D map          │    │  SR / EN language toggle     │   │
│  │  fill-extrusion  │    │  Resizable info panel        │   │
│  │  energy classes  │    │  Mobile overlay              │   │
│  └────────┬─────────┘    └──────────────┬──────────────┘   │
│           │                             │                   │
│           │ fetch GeoJSON               │ fetch /api/chat   │
└───────────┼─────────────────────────────┼───────────────────┘
            │                             │
            ▼                             ▼
┌───────────────────┐        ┌────────────────────────────────┐
│  data/ (GeoJSON)  │        │   BACKEND (Render.com)         │
│                   │        │   backend/app.py (Flask)       │
│  buildings_       │        │                                │
│  processed.geojson│        │  - Structured spatial context  │
│                   │        │  - Domain guardrails           │
│  parks_           │        │  - SR/EN language switching    │
│  processed.geojson│        │  - OpenAI gpt-4o-mini          │
│                   │        │  - temperature=0.2             │
│  streets_         │        └──────────────┬─────────────────┘
│  processed.geojson│                       │
└───────────────────┘                       ▼
                               ┌────────────────────────┐
                               │      OpenAI API        │
                               │      gpt-4o-mini       │
                               └────────────────────────┘

Browser-side external calls:
  ┌─────────────────┐    ┌───────────────────┐
  │  MapTiler API   │    │  Open-Meteo API   │
  │  Base map style │    │  Live weather     │
  │  (tiles/style)  │    │  (no key needed)  │
  └─────────────────┘    └───────────────────┘
```

---

## Data Sources

| Source | Data | Type | Notes |
|--------|------|------|-------|
| **OpenStreetMap** (Geofabrik PBF) | Building footprints, parks, streets | Real | Serbia extract, ~226 MB |
| **OSM `building:levels` tag** | Floor count | Real | Present in 60.6% of buildings (5,030 / 8,326) |
| **OSM `addr:street`, `addr:housenumber`** | Building addresses | Real | Parsed from GDAL `other_tags` hstore string |
| **GHS-AGE R2025A** (JRC EU, Copernicus) | Construction epoch per asset | Real | 100 m resolution, Mollweide projection |
| **Open-Meteo API** | Temperature, humidity, UV, wind, precipitation | Real, live | Free, no API key, hourly updates |
| **EU building energy standards** | Reference kWh/m²/yr by construction period | Normative | Basis for energy intensity simulation |
| **Simulation** | Energy consumption (kWh/m²/yr, kWh/yr, kWh/floor) | **SIMULATED** | Clearly disclosed throughout |

---

## Methodology

### 1. Data Acquisition (01_fetch_osm.py)

OSM data was acquired as a Serbia-wide PBF extract from Geofabrik (~226 MB). The GDAL OSM driver built into `pyogrio` reads the file directly without an intermediate conversion step, with SQL filters applied per layer:

- `multipolygons WHERE building IS NOT NULL` → building footprints
- `multipolygons WHERE leisure = 'park'` → park polygons
- `lines WHERE highway IS NOT NULL` → street network

Spatial filter: bounding box `min_lat=44.790, max_lat=44.810, min_lon=20.455, max_lon=20.490`

Verified element counts (cross-checked against Overpass Turbo):

| Category | Count |
|----------|-------|
| Buildings | 8,306 |
| Buildings with `building:levels` tag | 5,030 (60.6%) |
| Parks | 31 |
| Street segments | 4,412 |

### 2. Asset Attribute Enrichment (02_process_data.py)

For each building polygon:

**Floor count:** regex extraction from GDAL `other_tags` hstore string (`"building:levels"=>"N"`), validated within 1–50 floor range; default 3 floors where absent. Buildings with footprint >5,000 m² and declared floors >12 are capped at 12 (validated against the University Clinical Centre of Serbia, the largest building in the dataset).

**Height:**
```
height_m = floor_count × 3.2 m
```

**Area:** geometry reprojected to UTM Zone 34N (EPSG:32634) before area computation.
```
base_area_m2  = footprint area (m²)
total_area_m2 = base_area_m2 × floor_count
```

**Address:** assembled from `addr:street` + `addr:housenumber`; fallback to OSM `name` tag.

### 3. Raster-to-Vector Spatial Join (03_ghsl_extract.py)

Dataset: **GHS-AGE R2025A** — Global Human Settlement Age, JRC EU / Copernicus, 2025. Resolution: 100 m, Mollweide projection (ESRI:54009).

For each building:
1. Compute centroid in WGS84
2. Transform to Mollweide via `pyproj`
3. Sample pixel value at centroid using `rasterio` (1×1 window read — no full raster load into memory)
4. Map code to construction epoch zone

| GHSL Code | Epoch | Zone | Energy Range (kWh/m²/yr) |
|-----------|-------|------|--------------------------|
| 0 | Not built-up | zone fallback | — |
| 1 | < 1975 | pre_1941 | 180–220 |
| 2 | 1975–1980 | 1960_1980 | 140–180 |
| 3–4 | 1980–1990 | 1980_2000 | 100–140 |
| 5–10 | 1990–2020 | post_2000 | 60–100 |

One manual correction: the **Temple of Saint Sava** (completed 2004) is misclassified by GHSL due to the surrounding pre-1975 block dominating its 100 m pixel. A targeted centroid bbox correction reclassifies it to `post_2000`; the corrected record is flagged with `ghsl_age_code = -1` for traceability.

`random.seed(42)` and `np.random.seed(42)` are set before energy sampling to ensure reproducibility across runs.

### 4. Energy Intensity Simulation

```
kwh_per_m2     = random.uniform(low, high)    # sampled within zone range
total_kwh_year  = kwh_per_m2 × total_area_m2
kwh_per_floor   = total_kwh_year / floor_count
```

Colour classification:

| Colour | Range | Hex |
|--------|-------|-----|
| 🟢 Green | < 80 kWh/m²/yr | `#2ecc71` |
| 🟡 Yellow | 80–150 kWh/m²/yr | `#f1c40f` |
| 🟠 Orange | 150–200 kWh/m²/yr | `#e67e22` |
| 🔴 Red | > 200 kWh/m²/yr | `#e74c3c` |

### 5. Visualisation (MapLibre GL JS)

- `fill-extrusion` layer: height from `height_m`, colour from `energy_color`
- Colour interpolation: energy classes at zoom ≤ 15, neutral `#d4c5a9` at zoom ≥ 17 — preserves readability at street level
- Single centralised click handler using `queryRenderedFeatures` with explicit priority: building > park > street — resolves polygon overlap conflicts
- Base style: MapTiler Streets v2

### 6. AI Assistant

**Model:** OpenAI `gpt-4o-mini` · **Temperature:** 0.2 · **Max tokens:** 600

The system prompt embeds a structured data context at startup: top 5 and bottom 5 buildings by total consumption (with coordinates), all parks with live meteorological readings sampled from Open-Meteo at server start, and the street inventory. This avoids per-request data fetching and keeps latency low.

Guardrails enforced via prompt:
- Responds only to questions within the spatial dataset scope; all out-of-domain requests receive a fixed refusal string
- Energy figures must always be described as simulated
- Cannot identify the oldest or newest individual building by name — the 100 m raster resolution constraint is explained to the user rather than papered over
- Output is plain prose; no Markdown formatting
- Map navigation: a `<fly>{"lng": ..., "lat": ..., "zoom": 17}` tag is appended for building responses, parsed by the frontend to animate the map to the referenced asset. Not used for parks or streets.
- Language: Serbian (Latin script) or English, controlled by a `lang` parameter sent with each request

---

## Potential Applications

The pipeline built here — geospatial asset ingestion, satellite raster join, per-asset attribute enrichment, real-time data feed integration, AI-assisted querying — is not specific to residential buildings. The same architecture maps directly onto:

**Energy infrastructure:**
Substation and transformer footprint analysis. Distribution network asset inventory enriched with age, capacity class, and inspection history. Demand-side load estimation tied to building stock characteristics in a service territory.

**Building energy compliance and retrofit planning:**
Large-scale identification of pre-retrofit building stock by construction epoch, gross floor area, and estimated energy intensity. Prioritisation of intervention across a portfolio of assets.

**Smart grid demand forecasting:**
Spatial aggregation of simulated or metered consumption at feeder or zone level. Integration with meteorological feeds for temperature-adjusted demand curves.

**Infrastructure Digital Twin:**
The same GeoJSON pipeline can ingest linear infrastructure (pipelines, cable routes, overhead lines) alongside polygon assets. The AI assistant pattern — structured context + domain guardrails + spatial navigation tags — extends to any asset class with addressable coordinates.

**Utility asset management:**
Per-asset age classification from satellite-derived datasets removes the dependency on complete and accurate utility records, which are rarely available for legacy infrastructure.

---

## Project Structure

```
BIM-DigitalTwin-AIBot/
│
├── data/
│   ├── buildings.geojson               # Raw OSM building polygons
│   ├── parks.geojson                   # Raw OSM park polygons
│   ├── streets.geojson                 # Raw OSM street lines
│   ├── buildings_processed.geojson     # Enriched buildings (energy, GHSL epoch)
│   ├── parks_processed.geojson         # Parks with computed area
│   └── streets_processed.geojson       # Streets with type, speed, one-way flag
│
├── scripts/
│   ├── 01_fetch_osm.py                 # PBF acquisition and GeoJSON export
│   ├── 02_process_data.py              # Attribute enrichment and energy simulation
│   └── 03_ghsl_extract.py             # Raster-to-vector join + manual corrections
│
├── frontend/
│   └── index.html                      # Single-file frontend (MapLibre + AI chat)
│
├── backend/
│   └── app.py                          # Flask REST API — OpenAI integration
│
├── .env                                # API keys — never commit
├── .gitignore
└── requirements.txt
```

---

## Installation & Local Setup

### Prerequisites

- Python 3.11+
- MapTiler API key (free): https://www.maptiler.com/
- OpenAI API key: https://platform.openai.com/api-keys
- GHS-AGE R2025A GeoTIFF in `data/GHLS/`: https://human-settlement.emergency.copernicus.eu/downloadWizard.php

### Setup

```bash
git clone https://github.com/mimicgoran/BIM-DigitalTwin-AIBot.git
cd BIM-DigitalTwin-AIBot

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux / macOS

pip install geopandas requests rasterio pyproj flask flask-cors openai python-dotenv
```

Create `.env` in the project root:
```
OPENAI_API_KEY=your_key_here
```

### Data Pipeline

```bash
python scripts/01_fetch_osm.py       # ~226 MB download, cached after first run
python scripts/02_process_data.py
python scripts/03_ghsl_extract.py    # requires GeoTIFF in data/GHLS/
```

### Run Locally

```bash
# Terminal 1
python backend/app.py

# Terminal 2
python -m http.server 8000
```

Open: `http://localhost:8000/frontend/index.html`

---

## Deployment

### Backend — Render.com (free tier)

1. Connect GitHub repository in Render dashboard
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `python backend/app.py`
4. **Environment variable:** `OPENAI_API_KEY`

The free tier spins down after 15 minutes of inactivity. A keep-alive ping to `/api/health` via [UptimeRobot](https://uptimerobot.com) (free, 5-minute interval) prevents cold starts.

### Frontend — GitHub Pages (free)

Repository → Settings → Pages → Deploy from branch `main`, root `/`.

Rebuilds automatically on every push to `main`.

---

## Known Limitations

| Issue | Cause | Status |
|-------|-------|--------|
| 97% of buildings assigned to the < 1975 epoch | GHSL 100 m pixel covers entire city blocks | Documented; AI explains the constraint |
| Energy figures are not real | No open per-building consumption database exists for Serbia | Labelled SIMULATED throughout; never presented otherwise |
| Weather readings nearly identical across parks | Study area is < 2 km² | Acceptable for neighbourhood-scale analysis |
| AI cannot name the oldest individual building | 100 m raster does not resolve individual asset dates | Prescribed explanation returned instead of a fabricated answer |
| Backend cold-start latency (~50 s) | Render.com free tier | Mitigated with UptimeRobot keep-alive |
| Temple of Saint Sava manually reclassified | Surrounding pre-1975 block dominates the GHSL pixel | Targeted correction in `03_ghsl_extract.py`; flagged with `ghsl_age_code = -1` |

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | MapLibre GL JS 4.7.1 | 3D rendering and interaction |
| Frontend | MapTiler Streets v2 | Base map tiles |
| Frontend | Open-Meteo API | Live weather (free, no key) |
| Frontend | Vanilla JS / HTML / CSS | UI, i18n, responsive layout |
| Backend | Flask + Flask-CORS | REST API |
| Backend | OpenAI Python SDK | GPT-4o-mini integration |
| Backend | python-dotenv | Secrets management |
| Processing | geopandas + pyogrio | Spatial I/O and analysis |
| Processing | rasterio | GeoTIFF raster sampling |
| Processing | pyproj | CRS transformation |
| Processing | shapely | Geometric operations |

**Open data licences:**

| Source | Licence |
|--------|---------|
| OpenStreetMap | ODbL |
| GHS-AGE R2025A (JRC EU) | CC BY 4.0 |
| Open-Meteo | CC BY 4.0 |

---

## Data Disclaimer

Energy consumption values shown in this application are **simulated** using EU building energy performance reference ranges applied to satellite-derived construction epoch data. They are not measured, not verified against utility records, and should not be used for compliance, procurement, or investment decisions.

All geometric data, addresses, building heights, meteorological readings, and construction epoch classifications are sourced from verified open datasets as listed above.
