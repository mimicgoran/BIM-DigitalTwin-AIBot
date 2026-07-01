"""
backend/app.py

Flask API za GridTwin AI asistent.
Prima pitanja od frontend-a, šalje ih OpenAI API-ju sa strogim
system prompt-om koji ograničava odgovore isključivo na podatke o Vračaru.

Pokretanje:
  pip install flask flask-cors openai python-dotenv
  python backend/app.py
"""

from pathlib import Path
import json
from flask import Flask, request, jsonify
from flask_cors import CORS
from openai import OpenAI
from dotenv import load_dotenv
import os
import geopandas as gpd
import requests as http_requests

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

app = Flask(__name__)
CORS(app)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

def fetch_park_weather(lat: float, lon: float) -> dict:
    """Povlači trenutne meteorološke podatke sa Open-Meteo za datu lokaciju."""
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m,uv_index,precipitation_probability"
        )
        r = http_requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json().get("current", {})
    except Exception as e:
        return {"error": str(e)}


# ── Učitaj podatke jednom pri startu servera ───────────────────
def build_context() -> str:
    try:
        buildings = gpd.read_file(DATA_DIR / "buildings_processed.geojson")
        parks     = gpd.read_file(DATA_DIR / "parks_processed.geojson")
        streets   = gpd.read_file(DATA_DIR / "streets_processed.geojson")
    except Exception as e:
        return f"Greška pri učitavanju podataka: {e}"

    total_b = len(buildings)
    avg_kwh = buildings["kwh_per_m2"].mean()

    sorted_b = buildings.sort_values("total_kwh_year", ascending=False)
    top5_rows = sorted_b.head(5)
    top5_txt = "\n".join(
        f"  - {r['address']}: {int(r['total_kwh_year']):,} kWh/god simulirano, "
        f"{r['kwh_per_m2']} kWh/m², {r['levels']} spratova, "
        f"koordinate: [{r.geometry.centroid.x:.5f}, {r.geometry.centroid.y:.5f}]"
        for _, r in top5_rows.iterrows()
    )

    bottom5_rows = sorted_b.tail(5)
    bottom5_txt = "\n".join(
        f"  - {r['address']}: {int(r['total_kwh_year']):,} kWh/god simulirano, "
        f"{r['kwh_per_m2']} kWh/m², {r['levels']} spratova, "
        f"koordinate: [{r.geometry.centroid.x:.5f}, {r.geometry.centroid.y:.5f}]"
        for _, r in bottom5_rows.iterrows()
    )

    zone_counts = buildings["age_zone"].value_counts().to_dict()

    park_list = []
    print("Povlačim meteorološke podatke za parkove sa Open-Meteo...")
    for _, p in parks.iterrows():
        name = p.get("name") or "Nepoznat"
        area = int(p.get("area_m2", 0))
        centroid = p.geometry.centroid
        weather = fetch_park_weather(centroid.y, centroid.x)
        if "error" not in weather:
            park_list.append(
                f"{name} ({area:,} m²) — "
                f"temperatura: {weather.get('temperature_2m', '?')}°C, "
                f"vlažnost: {weather.get('relative_humidity_2m', '?')}%, "
                f"UV: {weather.get('uv_index', '?')}, "
                f"vetar: {weather.get('wind_speed_10m', '?')} km/h, "
                f"padavine: {weather.get('precipitation_probability', '?')}%"
            )
        else:
            park_list.append(f"{name} ({area:,} m²) — meteorološki podaci nedostupni")
    print(f"Meteorološki podaci učitani za {len(park_list)} parkova.")

    oneway = streets[streets["oneway"] == "yes"]["name"].dropna().unique().tolist()
    oneway_txt = ", ".join(oneway[:10]) if oneway else "Nema podataka"

    context = f"""
GRIDTWIN VRAČAR — PODACI (stvarni OSM + GHSL + simulirana energetika)

ZGRADE:
- Ukupno zgrada: {total_b}
- Prosečna simulirana potrošnja: {avg_kwh:.1f} kWh/m²/god
- Top 5 potrošača (simulirano):
{top5_txt}
- Top 5 najmanje potrošača (simulirano):
{bottom5_txt}
- Distribucija po epohi izgradnje (GHSL AGE R2025A):
  pre 1975: {zone_counts.get('pre_1941', 0)} zgrada
  1975–1980: {zone_counts.get('1960_1980', 0)} zgrada
  1980–1990: {zone_counts.get('1980_2000', 0)} zgrada
  posle 1990: {zone_counts.get('posle_2000', 0)} zgrada

PARKOVI ({len(parks)} ukupno):
{chr(10).join('  - ' + p for p in park_list)}

ULICE:
- Ukupno segmenata: {len(streets)}
- Jednosmerne ulice (uzorak): {oneway_txt}

IZVORI PODATAKA:
- Geometrije i atributi zgrada/parkova/ulica: OpenStreetMap
- Epoha izgradnje: GHS-AGE R2025A (JRC EU, 100m rezolucija)
- Meteorološki podaci: Open-Meteo API (stvarni, real-time)
- Energetska potrošnja: SIMULIRANA na osnovu EU building energy standarda
  (nije stvarno izmerena — koristi se isključivo za demonstraciju koncepta)
    """.strip()

    return context


CONTEXT = build_context()

SYSTEM_PROMPT = f"""Ti si AI asistent za GridTwin Vračar Digital Twin projekat.

STROGA PRAVILA — mora se poštovati bez izuzetka:

1. ODGOVARAŠ SAMO na pitanja koja se odnose na:
   - Zgrade na Vračaru (energetska potrošnja, spratovi, adrese, starost)
   - Parkove na Vračaru (nazivi, površine, meteorologija)
   - Ulice na Vračaru (tip, jednosmerne, ograničenje brzine)
   - Metodologiju projekta (šta je simulirano, šta su stvarni podaci)
   - Izvore podataka (OSM, GHSL, Open-Meteo)

2. AKO korisnik postavi pitanje koje NIJE vezano za gore navedene teme
   (politika, opšte znanje, pisanje koda, vesti, lične informacije, itd.),
   odgovaraš ISKLJUČIVO:
   "Mogu da odgovorim samo na pitanja vezana za GridTwin Vračar projekat:
   zgrade, parkove, ulice, energetiku i podatke o ovom kvartu.
   Za ostale teme koristite druge alate."

3. NIKAD ne izmišljaš podatke. Ako podatak nije u kontekstu koji imaš,
   kažeš: "Taj podatak nije dostupan u GridTwin bazi za Vračar."

4. PARKOVI I TEMPERATURA — podaci o temperaturi za svaki park su dostupni
   u sekciji PARKOVI. Kada korisnik pita koji park je najhladniji ili
   najtopliji, UVEK poređaj parkove po temperaturi iz konteksta i daj
   konkretan odgovor. Ignorisi parkove bez naziva (nan).
   Primer: "Najhladniji park na Vračaru je Црвени крст sa 26.1°C."

4. GHSL AGE OGRANIČENJE — važno: GHS-AGE raster ima rezoluciju 100m,
   što znači da jedan piksel pokriva oko 10.000 m² i sadrži više zgrada.
   Sve zgrade u tom pikselu dobijaju istu epohу izgradnje.
   Zbog toga NE MOŽEMO znati koja je konkretno najstarija ili najnovija
   zgrada — znamo samo da koja zona/epoha dominira u tom delu kvarta.
   Ako korisnik pita "koja je najstarija zgrada", odgovori:
   "GHS-AGE raster koji koristimo ima rezoluciju 100m i daje epohу izgradnje
   po zoni, ne po individualnoj zgradi. Mogu da ti kažem da 8068 zgrada
   pripada epohi pre 1975, ali ne mogu da izdvojim konkretno najstariju."

4. Energetsku potrošnju UVEK navodi kao simuliranu vrednost —
   nikad je ne predstavljaj kao stvarno izmerenu.

5. Odgovaraš na srpskom jeziku (latinica), koncizno, u prirodnom tekstu.
   ZABRANJENO: markdown bold (**tekst**), bullet liste sa crticama, naslovi sa #.
   Piši kao što bi govorio — kratke rečenice, bez formatiranja.
   Primer dobrog odgovora: "Zgrada koja troši najviše energije na Vračaru nalazi se u ulici Др Косте Тодоровића 3. Simulirana potrošnja iznosi 33.402.120 kWh godišnje."
   Primer lošeg odgovora: "**Др Косте Тодоровића 3**: 33,402,120 kWh/god, 181.1 kWh/m²"

6. Kada identifikuješ konkretan objekat (zgradu ili park), na KRAJU odgovora
   dodaj SAMO ovaj JSON tag sa tačnim koordinatama iz konteksta:
   <fly>{{"lng": LONGITUDE, "lat": LATITUDE, "zoom": 17}}</fly>
   Koordinate su navedene u podacima za svaki objekat u formatu [lng, lat].
   Ako ne znaš koordinate, NE dodaj fly tag.

PODACI O VRAČARU KOJE IMAŠ:
{CONTEXT}
"""


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(silent=True)
    if not body or "message" not in body:
        return jsonify({"error": "Nedostaje 'message' u body-ju"}), 400

    user_message = str(body["message"]).strip()
    lang = str(body.get("lang", "sr")).strip().lower()

    if not user_message:
        return jsonify({"error": "Poruka je prazna"}), 400

    if len(user_message) > 500:
        return jsonify({"error": "Poruka je predugačka (max 500 karaktera)"}), 400

    lang_instruction = (
        "Respond in English (Latin script)."
        if lang == "en"
        else "Odgovaraš na srpskom jeziku (latinica)."
    )

    system_with_lang = SYSTEM_PROMPT.replace(
        "5. Odgovaraš na srpskom jeziku (latinica), koncizno, u prirodnom tekstu.",
        f"5. {lang_instruction} Koncizno, u prirodnom tekstu."
    )

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_with_lang},
                {"role": "user",   "content": user_message}
            ],
            max_tokens=600,
            temperature=0.2,
        )
        reply = response.choices[0].message.content
        return jsonify({"reply": reply})

    except Exception as e:
        return jsonify({"error": f"OpenAI greška: {str(e)}"}), 500


@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "data_loaded": "Greška" not in CONTEXT,
        "model": "gpt-4o-mini"
    })


if __name__ == "__main__":
    print("GridTwin AI backend pokrenut na http://localhost:5000")
    print(f"Kontekst učitan: {len(CONTEXT)} karaktera")
    app.run(debug=False, port=5000)
