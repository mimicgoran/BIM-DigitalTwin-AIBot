"""
01_fetch_osm.py (v3 — PBF + GDAL OSM driver)

Zaobilazi Overpass API (blokiran/nedostupan na nekim mrežama) tako što:
1. Preuzima ceo Srbija PBF ekstrakt sa Geofabrik-a (jednom, kešira lokalno)
2. Lokalno, preko GDAL OSM drivera (ugrađen u geopandas/pyogrio — bez
   dodatnih zavisnosti koje zahtevaju kompajliranje), izvlači samo Vračar
   (bbox) i samo relevantne slojeve: zgrade, parkove, ulice
3. Snima rezultat kao GeoJSON fajlove u data/ — isti izlaz kao i plan,
   samo bez zavisnosti od Overpass servera i bez pyrosm/cykhash problema
   sa kompajliranjem na Windows-u.

Potvrđeni brojevi elemenata (Overpass Turbo test 30.06.2026, za poređenje):
  - zgrade (building):              8306
  - zgrade sa building:levels:      5030 (60.6%)
  - ulice (highway):                4412
  - parkovi (leisure=park):         31

Pokretanje:
  pip install geopandas requests
  python scripts/01_fetch_osm.py
"""

from pathlib import Path

import geopandas as gpd
import requests

# Bounding box Vračara: (min_lon, min_lat, max_lon, max_lat)
BBOX = (20.455, 44.790, 20.490, 44.810)

PBF_URL = "https://download.geofabrik.de/europe/serbia-latest.osm.pbf"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PBF_PATH = DATA_DIR / "serbia-latest.osm.pbf"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def download_pbf():
    """Preuzima Srbija PBF ako već ne postoji lokalno (fajl je ~150-250MB)."""
    if PBF_PATH.exists():
        size_mb = PBF_PATH.stat().st_size / (1024 * 1024)
        print(f"PBF fajl već postoji ({size_mb:.1f} MB), preskačem preuzimanje: {PBF_PATH}")
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Preuzimam {PBF_URL} ...")
    with requests.get(PBF_URL, headers=HEADERS, stream=True, timeout=300) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(PBF_PATH, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {downloaded / (1024*1024):.0f}/{total / (1024*1024):.0f} MB ({pct:.0f}%)", end="")
    print(f"\nPreuzeto: {PBF_PATH}")


def extract_vracar():
    """
    Čita PBF direktno preko GDAL OSM drivera (ugrađen u pyogrio/geopandas),
    sa SQL filterom i bbox-om — GDAL čita samo relevantan deo fajla, ne ceo PBF u memoriju.

    GDAL OSM driver organizuje podatke u slojeve: points, lines,
    multilinestrings, multipolygons, other_relations.
    Zgrade i parkovi (poligoni) su u 'multipolygons', ulice (linije) u 'lines'.
    """
    print("\nČitam zgrade (multipolygons, building IS NOT NULL)...")
    buildings = gpd.read_file(
        str(PBF_PATH),
        sql="SELECT * FROM multipolygons WHERE building IS NOT NULL",
        sql_dialect="OGRSQL",
        bbox=BBOX,
    )

    print("Čitam parkove (multipolygons, leisure = 'park')...")
    parks = gpd.read_file(
        str(PBF_PATH),
        sql="SELECT * FROM multipolygons WHERE leisure = 'park'",
        sql_dialect="OGRSQL",
        bbox=BBOX,
    )

    print("Čitam ulice (lines, highway IS NOT NULL)...")
    streets = gpd.read_file(
        str(PBF_PATH),
        sql="SELECT * FROM lines WHERE highway IS NOT NULL",
        sql_dialect="OGRSQL",
        bbox=BBOX,
    )

    return buildings, parks, streets


def report_counts(buildings, parks, streets):
    b_count = len(buildings) if buildings is not None else 0
    p_count = len(parks) if parks is not None else 0
    s_count = len(streets) if streets is not None else 0

    levels_count = 0
    if buildings is not None and "other_tags" in buildings.columns:
        levels_count = buildings["other_tags"].fillna("").str.contains('"building:levels"').sum()

    print("\nIzvučeno elemenata:")
    print(f"  zgrade: {b_count}")
    print(f"  zgrade sa building:levels: {levels_count}")
    print(f"  parkovi: {p_count}")
    print(f"  ulice (segmenti): {s_count}")

    expected = {"zgrade": 8306, "parkovi": 31, "ulice": 4412}
    actual = {"zgrade": b_count, "parkovi": p_count, "ulice": s_count}
    print("\nNapomena: brojevi se NEĆE poklopiti tačno sa Overpass Turbo testom —")
    print("Overpass je brojao 'way' objekte (segmente puta), a GDAL OSM driver")
    print("može vratiti drugačiju granulaciju (spojeni/podeljeni segmenti). Ovo je")
    print("očekivano i nije greška, ali ako je razlika DRASTIČNA (10x+), javi.")
    for k in expected:
        print(f"  {k}: Overpass={expected[k]}, PBF ekstrakt={actual[k]}")


def main():
    download_pbf()
    buildings, parks, streets = extract_vracar()
    report_counts(buildings, parks, streets)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if buildings is not None and len(buildings) > 0:
        buildings.to_file(DATA_DIR / "buildings.geojson", driver="GeoJSON")
        print(f"\nSnimljeno: {DATA_DIR / 'buildings.geojson'}")
    else:
        print("\nUPOZORENJE: nema podataka o zgradama — proveri bbox/PBF fajl.")

    if parks is not None and len(parks) > 0:
        parks.to_file(DATA_DIR / "parks.geojson", driver="GeoJSON")
        print(f"Snimljeno: {DATA_DIR / 'parks.geojson'}")
    else:
        print("UPOZORENJE: nema podataka o parkovima — proveri bbox/PBF fajl.")

    if streets is not None and len(streets) > 0:
        streets.to_file(DATA_DIR / "streets.geojson", driver="GeoJSON")
        print(f"Snimljeno: {DATA_DIR / 'streets.geojson'}")
    else:
        print("UPOZORENJE: nema podataka o ulicama — proveri bbox/PBF fajl.")


if __name__ == "__main__":
    main()