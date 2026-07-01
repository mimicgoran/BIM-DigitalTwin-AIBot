"""
03_ghsl_extract.py

Čita GHS-AGE R2025A raster i za centroid svake zgrade iz
buildings_processed.geojson izvlači piksel vrednost (epoch kod),
mapira je na starosnu zonu, i ažurira age_zone i energetske kolone.

GHS-AGE lookup (iz CSV legende):
  0  → not built-up   → fallback na zonsku klasifikaciju
  1  → < 1975         → age_zone: "pre_1941"    (180-220 kWh/m²/god)
  2  → 1975-1980      → age_zone: "1960_1980"   (140-180 kWh/m²/god)
  3  → 1980-1985      → age_zone: "1980_2000"   (100-140 kWh/m²/god)
  4  → 1985-1990      → age_zone: "1980_2000"   (100-140 kWh/m²/god)
  5  → 1990-1995      → age_zone: "posle_2000"  ( 60-100 kWh/m²/god)
  6  → 1995-2000      → age_zone: "posle_2000"  ( 60-100 kWh/m²/god)
  7  → 2000-2005      → age_zone: "posle_2000"  ( 60-100 kWh/m²/god)
  8  → 2005-2010      → age_zone: "posle_2000"  ( 60-100 kWh/m²/god)
  9  → 2010-2015      → age_zone: "posle_2000"  ( 60-100 kWh/m²/god)
  10 → 2015-2020      → age_zone: "posle_2000"  ( 60-100 kWh/m²/god)

NAPOMENA: GHS-AGE je 100m rezolucija — jedan piksel pokriva ~10,000m²,
što znači da jedna vrednost može pokriti više zgrada. Tačnost je
odgovarajuća za kvartovsku/zonsku analizu, ne za individualnu zgradu.
Energetska potrošnja ostaje SIMULIRANA.

Pokretanje:
  python scripts/03_ghsl_extract.py
"""

import glob
import random
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.windows import from_bounds

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
GHSL_DIR = DATA_DIR / "GHLS"

random.seed(42)
np.random.seed(42)

# GHS-AGE kod → starosna zona
AGE_CODE_TO_ZONE = {
    0:  None,          # not built-up → fallback
    1:  "pre_1941",    # < 1975
    2:  "1960_1980",   # 1975-1980
    3:  "1980_2000",   # 1980-1985
    4:  "1980_2000",   # 1985-1990
    5:  "posle_2000",  # 1990-1995
    6:  "posle_2000",  # 1995-2000
    7:  "posle_2000",  # 2000-2005
    8:  "posle_2000",  # 2005-2010
    9:  "posle_2000",  # 2010-2015
    10: "posle_2000",  # 2015-2020
}

ENERGY_RANGES = {
    "pre_1941":   (180, 220),
    "1960_1980":  (140, 180),
    "1980_2000":  (100, 140),
    "posle_2000": (60,  100),
}


def energy_color(kwh_per_m2: float) -> str:
    if kwh_per_m2 < 80:
        return "#2ecc71"
    elif kwh_per_m2 < 150:
        return "#f1c40f"
    elif kwh_per_m2 < 200:
        return "#e67e22"
    else:
        return "#e74c3c"


def find_age_tif() -> Path:
    tifs = [Path(f) for f in glob.glob(str(GHSL_DIR / "*.tif")) if "AGE" in f]
    if not tifs:
        raise FileNotFoundError(f"Nije pronađen GHS-AGE TIF u {GHSL_DIR}")
    return tifs[0]


def main():
    age_tif = find_age_tif()
    print(f"Koristim AGE raster: {age_tif.name}")

    print("Učitavam buildings_processed.geojson...")
    gdf = gpd.read_file(DATA_DIR / "buildings_processed.geojson")
    print(f"Ukupno zgrada: {len(gdf)}")

    # Transformer: WGS84 → Mollweide (CRS rastera)
    # Raster nema EPSG kod (CRS: None) ali je Mollweide ESRI:54009
    mollweide_wkt = (
        'PROJCS["World_Mollweide",'
        'GEOGCS["WGS 84",DATUM["WGS_1984",'
        'SPHEROID["WGS 84",6378137,298.257223563]],'
        'PRIMEM["Greenwich",0],UNIT["Degree",0.0174532925199433]],'
        'PROJECTION["Mollweide"],'
        'PARAMETER["central_meridian",0],'
        'PARAMETER["false_easting",0],'
        'PARAMETER["false_northing",0],'
        'UNIT["Meter",1]]'
    )
    transformer = Transformer.from_crs("EPSG:4326", mollweide_wkt, always_xy=True)

    age_zones = []
    kwh_per_m2_list = []
    total_kwh_list = []
    kwh_per_floor_list = []
    colors = []
    ghsl_codes = []
    fallback_count = 0

    with rasterio.open(age_tif) as src:
        print("Ekstraktujem AGE vrednosti za centroide zgrada...")
        for idx, row in gdf.iterrows():
            centroid = row.geometry.centroid
            mx, my = transformer.transform(centroid.x, centroid.y)

            # Čitaj piksel vrednost za tačku (window 1x1)
            try:
                py, px = src.index(mx, my)
                window = rasterio.windows.Window(px, py, 1, 1)
                val = int(src.read(1, window=window)[0, 0])
            except Exception:
                val = 0

            ghsl_codes.append(val)
            zone = AGE_CODE_TO_ZONE.get(val, None)

            # Fallback: zadrži postojeću zonsku klasifikaciju iz 02_process_data.py
            if zone is None:
                zone = row["age_zone"]
                fallback_count += 1

            age_zones.append(zone)

            low, high = ENERGY_RANGES[zone]
            kwh = round(random.uniform(low, high), 1)
            total = round(kwh * row["total_area_m2"])

            kwh_per_m2_list.append(kwh)
            total_kwh_list.append(total)
            kwh_per_floor_list.append(round(total / row["levels"]) if row["levels"] > 0 else total)
            colors.append(energy_color(kwh))

    gdf["ghsl_age_code"] = ghsl_codes
    gdf["age_zone"] = age_zones
    gdf["kwh_per_m2"] = kwh_per_m2_list
    gdf["total_kwh_year"] = total_kwh_list
    gdf["kwh_per_floor"] = kwh_per_floor_list
    gdf["energy_color"] = colors

    # ── Ručne korekcije poznatih zgrada ───────────────────────────
    # Hram Svetog Save: završen 2004, GHSL piksel (100m) ga svrstava u pre-1975
    # zbog okolnog bloka. Ručno korigujemo na posle_2000 zonu.
    # OSM adresa: nema addr:street, identifikujemo po osm_id ili lokaciji.
    hram_mask = (
        (gdf.geometry.centroid.x.between(20.4680, 20.4710)) &
        (gdf.geometry.centroid.y.between(44.7985, 44.8005))
    )
    if hram_mask.sum() > 0:
        low, high = ENERGY_RANGES["posle_2000"]
        kwh = round(random.uniform(low, high), 1)
        gdf.loc[hram_mask, "age_zone"]      = "posle_2000"
        gdf.loc[hram_mask, "ghsl_age_code"] = -1  # oznaka: ručna korekcija
        gdf.loc[hram_mask, "kwh_per_m2"]    = kwh
        gdf.loc[hram_mask, "total_kwh_year"] = (
            gdf.loc[hram_mask, "total_area_m2"] * kwh
        ).round()
        gdf.loc[hram_mask, "kwh_per_floor"] = (
            gdf.loc[hram_mask, "total_kwh_year"] / gdf.loc[hram_mask, "levels"]
        ).round()
        gdf.loc[hram_mask, "energy_color"] = energy_color(kwh)
        print(f"\nRučna korekcija primenjena na {hram_mask.sum()} zgrada/u (Hram Svetog Save zona).")
    else:
        print("\nUPOZORENJE: Hram Svetog Save nije pronađen u bbox korekciji — proveri koordinate.")

    print(f"\nFallback na zonsku klasifikaciju: {fallback_count} zgrada "
          f"({fallback_count/len(gdf)*100:.1f}%)")

    print("\nDistribucija po GHS-AGE kodovima:")
    from collections import Counter
    code_counts = Counter(ghsl_codes)
    epoch_labels = {
        0: "not built-up", 1: "< 1975", 2: "1975-1980", 3: "1980-1985",
        4: "1985-1990", 5: "1990-1995", 6: "1995-2000", 7: "2000-2005",
        8: "2005-2010", 9: "2010-2015", 10: "2015-2020"
    }
    for code in sorted(code_counts):
        label = epoch_labels.get(code, f"kod {code}")
        print(f"  {label}: {code_counts[code]} zgrada")

    print("\nDistribucija po starosnim zonama:")
    zone_counts = Counter(age_zones)
    for zone, cnt in zone_counts.most_common():
        print(f"  {zone}: {cnt} zgrada")

    print("\nStatistike potrošnje:")
    print(f"  Prosečna: {sum(kwh_per_m2_list)/len(kwh_per_m2_list):.1f} kWh/m²/god")
    max_idx = total_kwh_list.index(max(total_kwh_list))
    print(f"  Najveći potrošač: {gdf.iloc[max_idx]['address']} "
          f"({max(total_kwh_list):,} kWh/god)")

    out_path = DATA_DIR / "buildings_processed.geojson"
    gdf.to_file(out_path, driver="GeoJSON")
    print(f"\nAžurirano: {out_path}")


if __name__ == "__main__":
    main()