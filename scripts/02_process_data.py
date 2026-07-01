"""
02_process_data.py

Obrada sirovih GeoJSON fajlova iz KORAKA 1:
- Izvlači building:levels, adresu, godinu izgradnje iz other_tags stringa
- Izračunava visinu zgrade (levels * 3.2m)
- Simulira potrošnju energije po EU standardima (po starosnoj zoni)
- Izvozi buildings_processed.geojson spreman za MapLibre GL JS

Starosne zone Vračara (bez GHSL rastera, zonska klasifikacija):
  - Centar kvarta (bliže Slaviji):   pre 1941  → 180-220 kWh/m²/god
  - Srednji pojas:                   1960-1980 → 140-180 kWh/m²/god
  - Periferija (bliže Autokomandi):  1980-2000 → 100-140 kWh/m²/god
  - Novogradnja (sporadično):        posle 2000 → 60-100 kWh/m²/god

NAPOMENA: Energetska potrošnja je SIMULIRANA na osnovu EU building energy
standards i prostorne klasifikacije — nije stvarno izmerena.

Pokretanje:
  python scripts/02_process_data.py
"""

import random
import re
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# Centroid Vračara — referentna tačka za zoniranje starosti zgrada
VRACAR_CENTER = Point(20.470, 44.800)

# Seed za reproduktivnost (isti rezultati pri svakom pokretanju)
random.seed(42)
np.random.seed(42)


# ---------------------------------------------------------------------------
# Pomoćne funkcije
# ---------------------------------------------------------------------------

def parse_other_tags(other_tags_str: str) -> dict:
    """
    Parsira GDAL OSM 'other_tags' hstore string u Python dict.
    Format: "key1"=>"value1","key2"=>"value2"
    """
    if not other_tags_str or not isinstance(other_tags_str, str):
        return {}
    pattern = r'"([^"]+)"=>"([^"]*)"'
    return dict(re.findall(pattern, other_tags_str))


def get_building_levels(row) -> int:
    """Vraća broj spratova iz other_tags, sa defaultom 3 ako nedostaje."""
    tags = parse_other_tags(row.get("other_tags", ""))
    levels_str = tags.get("building:levels", "").strip()
    try:
        levels = int(float(levels_str))
        if 1 <= levels <= 50:  # odbaci nerealne vrednosti
            return levels
    except (ValueError, TypeError):
        pass
    return 3  # default


def get_address(row) -> str:
    """Sastavlja adresu iz other_tags ili name kolone."""
    tags = parse_other_tags(row.get("other_tags", ""))
    street = tags.get("addr:street", "")
    number = tags.get("addr:housenumber", "")
    if street:
        return f"{street} {number}".strip()
    if row.get("name"):
        return str(row["name"])
    return "Nepoznata adresa"


def assign_age_zone(centroid_lon: float, centroid_lat: float) -> str:
    """
    Dodeljuje starosnu zonu zgradi na osnovu distance od centra Vračara.
    Čisto prostorna aproksimacija — bez GHSL rastera.

    Zone:
      < 0.008 stepeni (~600m): centar → pre 1941
      0.008-0.015 (~1.1km):   srednji pojas → 1960-1980
      0.015-0.022 (~1.6km):   periferija → 1980-2000
      > 0.022:                 novogradnja → posle 2000
    """
    point = Point(centroid_lon, centroid_lat)
    dist = VRACAR_CENTER.distance(point)

    if dist < 0.008:
        return "pre_1941"
    elif dist < 0.015:
        return "1960_1980"
    elif dist < 0.022:
        return "1980_2000"
    else:
        return "posle_2000"


def simulate_energy(age_zone: str, area_m2: float) -> dict:
    """
    Simulira godišnju potrošnju energije na osnovu starosne zone i površine.

    Opsezi kWh/m²/god:
      pre_1941:   180-220
      1960_1980:  140-180
      1980_2000:  100-140
      posle_2000:  60-100

    Vraća dict sa kWh_per_m2 i total_kwh_year.
    """
    ranges = {
        "pre_1941":   (180, 220),
        "1960_1980":  (140, 180),
        "1980_2000":  (100, 140),
        "posle_2000": (60,  100),
    }
    low, high = ranges.get(age_zone, (140, 180))
    kwh_per_m2 = round(random.uniform(low, high), 1)
    total_kwh = round(kwh_per_m2 * area_m2)
    return {"kwh_per_m2": kwh_per_m2, "total_kwh_year": total_kwh}


def energy_color(kwh_per_m2: float) -> str:
    """Vraća boju za MapLibre fill-extrusion na osnovu potrošnje."""
    if kwh_per_m2 < 80:
        return "#2ecc71"   # zelena
    elif kwh_per_m2 < 150:
        return "#f1c40f"   # žuta
    elif kwh_per_m2 < 200:
        return "#e67e22"   # narandžasta
    else:
        return "#e74c3c"   # crvena


# ---------------------------------------------------------------------------
# Glavna obrada
# ---------------------------------------------------------------------------

def process_buildings(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print(f"Obrađujem {len(gdf)} zgrada...")

    # Reprojekcija u UTM zone 34N za tačno računanje površine u m²
    gdf_utm = gdf.to_crs(epsg=32634)

    results = []
    for idx, row in gdf_utm.iterrows():
        # Površina osnove zgrade u m²
        base_area = row.geometry.area

        # Broj spratova i visina
        levels = get_building_levels(row)

        # Cap za velike komplekse: OSM ponekad unosi ukupnu visinu višekrilnog
        # kompleksa kao levels jednog poligona, što daje nerealne površine.
        # Za zgrade sa osnovom > 5000m² i levels > 12, ograničavamo na 12.
        # (UKCS nova zgrada ima potvrđenih 12 spratova - Telegraf.rs 2022)
        if base_area > 5000 and levels > 12:
            levels = 12

        height_m = levels * 3.2

        # Ukupna bruto površina
        total_area = base_area * levels

        # Centroid u WGS84 za zoniranje
        centroid_wgs = gdf.loc[idx].geometry.centroid
        age_zone = assign_age_zone(centroid_wgs.x, centroid_wgs.y)

        # Simulirana potrošnja
        energy = simulate_energy(age_zone, total_area)

        # Adresa
        address = get_address(row)

        results.append({
            "osm_id": row.get("osm_id"),
            "address": address,
            "building_type": row.get("building", "yes"),
            "levels": levels,
            "height_m": height_m,
            "base_area_m2": round(base_area, 1),
            "total_area_m2": round(total_area, 1),
            "age_zone": age_zone,
            "kwh_per_m2": energy["kwh_per_m2"],
            "total_kwh_year": energy["total_kwh_year"],
            "energy_color": energy_color(energy["kwh_per_m2"]),
            "data_note": "Energy consumption: SIMULATED based on EU building energy standards",
            "geometry": gdf.loc[idx].geometry,  # originalna WGS84 geometrija
        })

    result_gdf = gpd.GeoDataFrame(results, crs="EPSG:4326")
    return result_gdf


def process_parks(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print(f"Obrađujem {len(gdf)} parkova...")
    gdf_utm = gdf.to_crs(epsg=32634)

    results = []
    for idx, row in gdf_utm.iterrows():
        tags = parse_other_tags(row.get("other_tags", ""))
        results.append({
            "osm_id": row.get("osm_id"),
            "name": row.get("name") or tags.get("name", "Nepoznat park"),
            "area_m2": round(row.geometry.area, 1),
            "geometry": gdf.loc[idx].geometry,
        })

    return gpd.GeoDataFrame(results, crs="EPSG:4326")


def process_streets(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    print(f"Obrađujem {len(gdf)} ulica...")

    results = []
    for idx, row in gdf.iterrows():
        tags = parse_other_tags(row.get("other_tags", ""))
        results.append({
            "osm_id": row.get("osm_id"),
            "name": row.get("name", ""),
            "highway": tags.get("highway") or row.get("highway", ""),
            "maxspeed": tags.get("maxspeed", ""),
            "oneway": tags.get("oneway", ""),
            "geometry": row.geometry,
        })

    return gpd.GeoDataFrame(results, crs="EPSG:4326")


def print_stats(buildings: gpd.GeoDataFrame):
    print("\n--- Statistike zgrada ---")
    print(f"Ukupno zgrada: {len(buildings)}")
    print(f"Prosečna visina: {buildings['height_m'].mean():.1f}m")
    print(f"Prosečna potrošnja: {buildings['kwh_per_m2'].mean():.1f} kWh/m²/god")
    print(f"Najveći potrošač: {buildings.loc[buildings['total_kwh_year'].idxmax(), 'address']} "
          f"({buildings['total_kwh_year'].max():,} kWh/god)")

    print("\nDistribucija po starosnim zonama:")
    for zone, count in buildings["age_zone"].value_counts().items():
        print(f"  {zone}: {count} zgrada")

    print("\nDistribucija po energetskim bojama:")
    for color, count in buildings["energy_color"].value_counts().items():
        label = {
            "#2ecc71": "zelena (<80)",
            "#f1c40f": "žuta (80-150)",
            "#e67e22": "narandžasta (150-200)",
            "#e74c3c": "crvena (>200)",
        }.get(color, color)
        print(f"  {label}: {count} zgrada")


def main():
    print("Učitavam sirove podatke...")
    buildings_raw = gpd.read_file(DATA_DIR / "buildings.geojson")
    parks_raw = gpd.read_file(DATA_DIR / "parks.geojson")
    streets_raw = gpd.read_file(DATA_DIR / "streets.geojson")

    buildings = process_buildings(buildings_raw)
    parks = process_parks(parks_raw)
    streets = process_streets(streets_raw)

    print_stats(buildings)

    out_b = DATA_DIR / "buildings_processed.geojson"
    out_p = DATA_DIR / "parks_processed.geojson"
    out_s = DATA_DIR / "streets_processed.geojson"

    buildings.to_file(out_b, driver="GeoJSON")
    parks.to_file(out_p, driver="GeoJSON")
    streets.to_file(out_s, driver="GeoJSON")

    print(f"\nSnimljeno:")
    print(f"  {out_b}")
    print(f"  {out_p}")
    print(f"  {out_s}")


if __name__ == "__main__":
    main()