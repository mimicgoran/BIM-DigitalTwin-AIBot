# GridTwin — Vračar Digital Twin

**An interactive 3D map of the Vračar district in Belgrade, Serbia, featuring an AI assistant, simulated building energy analysis, and real-time meteorological data.**

> This project demonstrates the practical application of GIS analysis, BIM concepts, open geospatial data, and artificial intelligence within the context of an urban Digital Twin.

---

## Table of Contents

- [About](#about)
- [Live Demo](#live-demo)
- [System Architecture](#system-architecture)
- [Data Sources](#data-sources)
- [Methodology](#methodology)
- [Project Structure](#project-structure)
- [Installation & Local Setup](#installation--local-setup)
- [Deployment](#deployment)
- [Known Limitations](#known-limitations)
- [Technology Stack](#technology-stack)
- [Data Disclaimer](#data-disclaimer)

---

## About

GridTwin Vračar is a Digital Twin prototype for an urban neighbourhood in Belgrade, Serbia. It integrates:

- **Real geospatial data** from OpenStreetMap (OSM) — building footprints and heights, parks, and streets
- **Real building age data** from the GHS-AGE R2025A raster dataset (Global Human Settlement Layer, JRC EU / Copernicus)
- **Real-time meteorological data** from the Open-Meteo API (temperature, humidity, UV index, wind speed, precipitation probability)
- **Simulated energy consumption** derived from EU building energy performance standards and GHSL-based construction epoch classification
- **A domain-restricted AI assistant** powered by OpenAI GPT-4o-mini, with strict prompt engineering to prevent hallucination and off-topic responses

The project is built exclusively on open and freely available data sources. All geometries, addresses, and building heights are real. The only simulated metric is building energy consumption, which is clearly disclosed throughout the interface and in every AI response.

---

## Live Demo

- **Frontend (GitHub Pages):** https://mimicgoran.github.io/BIM-DigitalTwin-AIBot/frontend/index.html
- **Backend API (Render.com):** https://bim-digitaltwin-aibot.onrender.com/api/health

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
│  │  MapLibre GL JS  │    │       AI Chat UI             │   │
│  │  3D Vračar map   │    │  SR / EN language toggle     │   │
│  │  fill-extrusion  │    │  Resizable info panel        │   │
│  │  by energy class │    │  Mobile overlay              │   │
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
│  processed.geojson│        │  - Context-rich system prompt  │
│                   │        │  - Strict domain guardrails    │
│  parks_           │        │  - SR/EN language switching    │
│  processed.geojson│        │  - OpenAI gpt-4o-mini          │
│                   │        │  - temperature=0.2             │
│  streets_         │        └──────────────┬─────────────────┘
│  processed.geojson│                       │
└───────────────────┘                       │ API call
                                            ▼
                               ┌────────────────────────┐
                               │      OpenAI API        │
                               │      gpt-4o-mini       │
                               └────────────────────────┘

External API calls (browser-side):
  ┌─────────────────┐    ┌───────────────────┐
  │  MapTiler API   │    │  Open-Meteo API   │
  │  Map base style │    │  Live weather     │
  │  (tiles/style)  │    │  (no key needed)  │
  └─────────────────┘    └───────────────────┘
```

---

## Data Sources

| Source | Data | Type | Notes |
|--------|------|------|-------|
| **OpenStreetMap** (Geofabrik PBF extract) | Building footprints, parks, streets | Real | Serbia-wide PBF, ~226 MB |
| **OSM `building:levels` tag** | Number of floors | Real | Present in 60.6% of buildings (5,030 / 8,326) |
| **OSM `addr:street`, `addr:housenumber`** | Building addresses | Real | Parsed from GDAL `other_tags` hstore string |
| **GHS-AGE R2025A** (JRC EU, Copernicus) | Construction epoch per building | Real | 100 m resolution, Mollweide projection |
| **Open-Meteo API** | Temperature, humidity, UV, wind, precipitation | Real, live | Free, no API key required, hourly updates |
| **EU building energy standards** | Reference kWh/m²/yr ranges by construction period | Normative | Basis for energy simulation |
| **Simulation** | Energy consumption (kWh/m²/yr, kWh/yr, kWh/floor) | **SIMULATED** | Not measured; clearly disclosed |

---

## Methodology

### 1. OSM Data Acquisition (01_fetch_osm.py)

OpenStreetMap data for Vračar was acquired in PBF (Protocolbuffer Binary Format) from the Geofabrik server (Serbia full extract, ~226 MB). Direct Overpass API access was unavailable during development due to network restrictions, so the following alternative approach was implemented:

- PBF file read using the **GDAL OSM driver** built into `pyogrio` (bundled with `geopandas`)
- SQL filters applied directly to GDAL layers: `multipolygons` for buildings and parks; `lines` for streets
- Spatial filter: bounding box `min_lat=44.790, max_lat=44.810, min_lon=20.455, max_lon=20.490`

Feature counts verified against Overpass Turbo prior to development:

| Category | Count |
|----------|-------|
| Buildings (total) | 8,306 |
| Buildings with `building:levels` tag | 5,030 (60.6%) |
| Parks (`leisure=park`) | 31 |
| Streets (`highway`) | 4,412 |

### 2. Data Processing (02_process_data.py)

For each building polygon from the OSM `multipolygons` layer:

**Floor count extraction:**
- Regex parsing of the GDAL `other_tags` hstore string for `"building:levels"=>"N"`
- Value validation: accepted range 1–50 floors
- Default: 3 floors for buildings lacking the tag
- Cap for large complexes: buildings with footprint >5,000 m² and >12 declared floors are capped at 12 floors (validated against real-world data for the University Clinical Centre of Serbia)

**Height calculation:**
```
height_m = floor_count × 3.2 m
```

**Area calculation:**
- Geometry reprojected to UTM Zone 34N (EPSG:32634) for metric precision
- `base_area_m2` = footprint area in m²
- `total_area_m2` = `base_area_m2 × floor_count`

**Address assembly:**
- Constructed from `addr:street` + `addr:housenumber` tags parsed from `other_tags`
- Fallback to OSM `name` tag when address tags are absent

**Energy per floor:**
```
kwh_per_floor = total_kwh_year / floor_count
```

### 3. GHSL AGE Raster Extraction (03_ghsl_extract.py)

Dataset: **GHS-AGE R2025A** (Global Human Settlement Age, JRC EU / Copernicus, 2025)
- Resolution: 100 m
- Projection: Mollweide (ESRI:54009)
- Epochs covered: 1975, 1980, 1985, 1990, 1995, 2000, 2005, 2010, 2015, 2020

Extraction procedure:
1. Compute centroid of each building polygon in WGS84
2. Transform centroid coordinates from WGS84 to Mollweide using `pyproj`
3. Read pixel value from the raster at centroid location using `rasterio` (1×1 window read, no full raster load)
4. Map pixel code to construction epoch zone via lookup table

| GHSL Code | Epoch | Zone ID | Energy Range (kWh/m²/yr) |
|-----------|-------|---------|--------------------------|
| 0 | Not built-up | fallback (zone-based) | — |
| 1 | < 1975 | pre_1941 | 180–220 |
| 2 | 1975–1980 | 1960_1980 | 140–180 |
| 3–4 | 1980–1990 | 1980_2000 | 100–140 |
| 5–10 | 1990–2020 | post_2000 | 60–100 |

**Manual corrections:**
The **Temple of Saint Sava** (construction completed 2004) is misclassified by GHSL as pre-1975 because the surrounding city block — built before 1975 — dominates the 100 m pixel. A targeted bbox correction (`lng 20.468–20.471, lat 44.798–44.800`) reclassifies it to the `post_2000` zone without affecting surrounding buildings.

**Reproducibility:** Both `random.seed(42)` and `np.random.seed(42)` are set before energy sampling, ensuring identical output across runs.

**Known limitation:** At 100 m resolution, a single pixel covers approximately 10,000 m² and may contain multiple buildings of different ages. All buildings sharing a pixel receive the same epoch. As a result, 97% of Vračar buildings receive code 1 (< 1975), which accurately reflects the neighbourhood's predominantly pre-war and socialist-era urban fabric, but precludes individual-building age identification. The AI assistant is explicitly instructed to explain this constraint rather than fabricate an answer.

### 4. Energy Consumption Simulation

Energy consumption is **simulated** based on EU building energy performance reference values. It is not measured and does not originate from any real utility or government energy database.

```
kwh_per_m2     = random.uniform(low, high)   # sampled within epoch zone range
total_kwh_year  = kwh_per_m2 × total_area_m2
kwh_per_floor   = total_kwh_year / floor_count
```

**Colour classification for MapLibre visualisation:**

| Colour | Range | Hex |
|--------|-------|-----|
| 🟢 Green | < 80 kWh/m²/yr | `#2ecc71` |
| 🟡 Yellow | 80–150 kWh/m²/yr | `#f1c40f` |
| 🟠 Orange | 150–200 kWh/m²/yr | `#e67e22` |
| 🔴 Red | > 200 kWh/m²/yr | `#e74c3c` |

### 5. 3D Visualisation (MapLibre GL JS)

- **Base style:** MapTiler Streets v2 (API key required)
- **Building layer:** `fill-extrusion` — height from `height_m`, colour from `energy_color`
- **Colour transition:** linear interpolation between zoom 15 (energy colours) and zoom 17 (neutral `#d4c5a9`), preserving building visibility at street level without colour distraction
- **Park layer:** `fill` (green, 25% opacity) + `line` outline
- **Street layer:** `line`
- **Click priority:** a single centralised `map.on('click')` handler uses `queryRenderedFeatures` with explicit priority order: building > park > street, resolving layer overlap conflicts (e.g. Temple of Saint Sava sitting within the Vračarski Plato park polygon)

### 6. AI Assistant

**Model:** OpenAI `gpt-4o-mini`  
**Temperature:** 0.2 — low value reduces hallucination risk  
**Max tokens:** 600  

The system prompt incorporates:
- Full data context: top 5 and bottom 5 buildings by total energy consumption (with coordinates), all 32 parks with live meteorological readings, street inventory
- Strict domain guardrails: the model is instructed to refuse all questions outside the Vračar dataset scope, returning a fixed refusal message
- Mandatory simulation disclosure: energy figures must always be described as simulated
- GHSL resolution constraint: explicit instruction not to identify the oldest/newest individual building by name, with a prescribed explanation of the 100 m raster limitation
- Language switching: Serbian (Latin script) or English, determined by the `lang` parameter sent with each request from the frontend
- Map navigation tags: the model appends a `<fly>{"lng": ..., "lat": ..., "zoom": 17}</fly>` tag for building responses only — never for parks — allowing the frontend to animate the map to the referenced location
- Output format: plain natural-language prose, no Markdown formatting

**Live weather in AI context:** On Flask server startup, Open-Meteo is queried for the centroid of each of the 32 parks. Temperature, humidity, UV index, wind speed, and precipitation probability are embedded in the system prompt context, enabling the AI to answer questions such as "which park is currently the coolest?" Context refreshes on each server restart.

### 7. Interface

- **Bilingual UI:** SR/EN toggle button in the header switches all labels, placeholder text, and AI response language simultaneously
- **Resizable split panel:** drag handle between the info panel and the chat area; minimum heights enforced (60 px info / 200 px chat)
- **Mobile responsive layout:** below 640 px viewport width, the layout switches to vertical stack (45% map / 55% chat); the info panel renders as a fixed full-width overlay above the chat, dismissible with a ✕ button
- **Live weather on park click:** a browser-side `fetch` to Open-Meteo is triggered on each park tap/click, displaying current conditions in the info panel

---

## Project Structure

```
BIM-DigitalTwin-AIBot/
│
├── data/                               # GeoJSON datasets (generated by scripts)
│   ├── buildings.geojson               # Raw OSM building polygons
│   ├── parks.geojson                   # Raw OSM park polygons
│   ├── streets.geojson                 # Raw OSM street lines
│   ├── buildings_processed.geojson     # Buildings with energy model & GHSL epoch
│   ├── parks_processed.geojson         # Parks with computed area
│   └── streets_processed.geojson       # Streets with type, speed limit, one-way flag
│
├── scripts/
│   ├── 01_fetch_osm.py                 # OSM PBF acquisition → GeoJSON export
│   ├── 02_process_data.py              # Floor count, height, area, energy simulation
│   └── 03_ghsl_extract.py             # GHSL AGE raster sampling + manual corrections
│
├── frontend/
│   └── index.html                      # Complete single-file frontend
│                                       # (MapLibre GL JS + AI chat + i18n + responsive)
│
├── backend/
│   └── app.py                          # Flask REST API (OpenAI integration)
│
├── .env                                # Secret keys — never commit
├── .gitignore                          # Excludes .env, PBF, GHSL rasters, .venv
└── requirements.txt                    # Python dependencies
```

---

## Installation & Local Setup

### Prerequisites

- Python 3.11+
- Git
- MapTiler API key (free developer tier): https://www.maptiler.com/
- OpenAI API key: https://platform.openai.com/api-keys
- GHS-AGE R2025A GeoTIFF downloaded to `data/GHLS/`: https://human-settlement.emergency.copernicus.eu/downloadWizard.php

### 1. Clone the repository

```bash
git clone https://github.com/mimicgoran/BIM-DigitalTwin-AIBot.git
cd BIM-DigitalTwin-AIBot
```

### 2. Create a virtual environment and install dependencies

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Linux / macOS
source .venv/bin/activate

pip install geopandas requests rasterio pyproj flask flask-cors openai python-dotenv
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```
OPENAI_API_KEY=your_api_key_here
```

### 4. Prepare the data pipeline

```bash
# Step 1: Download OSM data (~226 MB, cached after first run)
python scripts/01_fetch_osm.py

# Step 2: Process buildings, parks, and streets; run energy simulation
python scripts/02_process_data.py

# Step 3: Extract GHSL AGE epoch per building (requires GeoTIFF in data/GHLS/)
python scripts/03_ghsl_extract.py
```

### 5. Run locally

```bash
# Terminal 1 — Backend API
python backend/app.py

# Terminal 2 — Frontend static server
python -m http.server 8000
```

Open: `http://localhost:8000/frontend/index.html`

---

## Deployment

### Backend → Render.com (free tier)

1. Sign up at https://render.com using your GitHub account
2. New → Web Service → connect the `BIM-DigitalTwin-AIBot` repository
3. Configuration:
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python backend/app.py`
   - **Instance Type:** Free
4. Add Environment Variable: `OPENAI_API_KEY` = your key
5. Deploy

> **Cold start warning:** The free Render tier spins down after 15 minutes of inactivity. First requests after inactivity may take 50+ seconds. A keep-alive solution using [UptimeRobot](https://uptimerobot.com) (free) pinging the `/api/health` endpoint every 5 minutes is recommended.

### Frontend → GitHub Pages (free)

1. Repository → Settings → Pages
2. Source: Deploy from a branch → `main` → `/` (root)
3. Live URL: `https://mimicgoran.github.io/BIM-DigitalTwin-AIBot/frontend/index.html`

GitHub Pages automatically rebuilds on every push to `main`.

---

## Known Limitations

| Limitation | Root Cause | Handling |
|------------|------------|----------|
| 97% of buildings assigned to the < 1975 epoch | GHSL AGE 100 m resolution — one pixel covers an entire city block | Documented; AI explains the constraint to the user |
| Energy consumption is not real | No open per-building energy consumption database exists for Serbia | Clearly labelled SIMULATED throughout the UI and in every AI response |
| Weather data is nearly identical across all parks | Vračar is < 2 km² — inter-park temperature differences are 0.1–1 °C | Acceptable for neighbourhood-scale analysis |
| AI cannot identify the oldest/newest individual building | GHSL resolution does not support individual building dating | AI returns a prescribed explanation instead of a hallucinated answer |
| Backend cold-start latency (~50 s) | Render.com free tier spin-down policy | Mitigated with UptimeRobot keep-alive ping |
| Temple of Saint Sava manually reclassified | GHSL pixel dominated by surrounding pre-1975 block | Targeted bbox correction applied in `03_ghsl_extract.py`; flagged with `ghsl_age_code = -1` |

---

## Technology Stack

### Frontend

| Technology | Version | Purpose |
|------------|---------|---------|
| MapLibre GL JS | 4.7.1 | 3D map rendering and interaction |
| MapTiler Streets v2 | — | Base map tiles and style |
| Open-Meteo API | — | Live weather data (free, no key required) |
| Vanilla JS / HTML / CSS | — | UI components, i18n, responsive layout |

### Backend

| Technology | Purpose |
|------------|---------|
| Python 3.11 | Data processing scripts and API server |
| Flask | Lightweight REST API framework |
| Flask-CORS | Cross-Origin Resource Sharing headers |
| OpenAI Python SDK | GPT-4o-mini integration |
| python-dotenv | Secure environment variable management |

### Data Processing

| Library | Purpose |
|---------|---------|
| geopandas | Geospatial data processing and GeoJSON I/O |
| pyogrio | GDAL OSM driver for PBF file reading |
| rasterio | GeoTIFF raster reading (GHSL AGE) |
| pyproj | Coordinate reference system transformation |
| shapely | Geometric operations (centroids, areas) |
| numpy / pandas | Numerical and tabular data processing |

### Open Data Licences

| Source | Licence |
|--------|---------|
| OpenStreetMap | ODbL (Open Database Licence) |
| GHS-AGE R2025A (JRC EU) | CC BY 4.0 |
| Open-Meteo | CC BY 4.0 |
| EU building energy standards | Publicly available |

---

## Data Disclaimer

This project uses **simulated energy consumption values** solely for the purpose of demonstrating Digital Twin and GIS visualisation concepts. The kWh/m²/yr and kWh/yr figures shown in the interface are **not measured, not verified, and not sourced from any official energy database**. They are generated by a statistical model based on EU reference standards and GHSL-derived construction epoch classification.

All geometric data (building footprints, park boundaries, street networks), addresses, building heights, meteorological readings, and construction epoch classifications are sourced from verified open datasets as listed in the Data Sources section above.

---

*Developed as a research prototype exploring the application of Digital Twin methodology, open geospatial data, and AI-assisted spatial analysis in urban planning contexts.*
