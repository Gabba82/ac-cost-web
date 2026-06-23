#!/usr/bin/env python3
"""
AC Cost Web — servidor Flask
Puerto: 5656
"""

import os, json, time, requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

TZ              = ZoneInfo("Europe/Madrid")
ESIOS_TOKEN     = os.environ.get("ESIOS_TOKEN", "")
AEMET_TOKEN     = os.environ.get("AEMET_TOKEN", "")
ESIOS_BASE      = "https://api.esios.ree.es/indicators"
AEMET_BASE      = "https://opendata.aemet.es/opendata/api"
ESIOS_INDICATOR = 1001
GEO_PENINSULA   = 8741
PROMETHEUS_URL  = os.environ.get("PROMETHEUS_URL", "http://observatorio-prometheus:9090")

CONFIG_FILE  = os.environ.get("CONFIG_FILE", "/config/settings.json")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "/config/history.json")

MACHINES = [
    {"id": "mitsubishi_grande",  "label": "Mitsubishi MSZ-HR35VF", "kw_frio": 1.21, "kw_calor": 0.975},
    {"id": "mitsubishi_pequena", "label": "Mitsubishi MSZ-HR25VF",  "kw_frio": 0.80, "kw_calor": 0.850},
    {"id": "lg_viejita",         "label": "LG AS-H126RKA2",          "kw_frio": 1.30, "kw_calor": 1.20},
]

DEFAULT_SETTINGS = {
    "aemet_municipio":  "08200",
    "aemet_municipio_nombre": "Sant Boi de Llobregat",
    "prometheus_url":   "http://observatorio-prometheus:9090",
    "bono_social_pct":  42.5,
}

# ── Caché ────────────────────────────────────────────────────────────────────
_cache = {}
def cache_get(key):
    e = _cache.get(key)
    return e["val"] if e and time.time() < e["exp"] else None
def cache_set(key, val, ttl=3600):
    _cache[key] = {"val": val, "exp": time.time() + ttl}

# ── Settings ─────────────────────────────────────────────────────────────────
def load_settings():
    try:
        with open(CONFIG_FILE) as f:
            s = json.load(f)
            return {**DEFAULT_SETTINGS, **s}
    except Exception:
        return DEFAULT_SETTINGS.copy()

def save_settings(data):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    current = load_settings()
    current.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(current, f, indent=2, ensure_ascii=False)
    return current

# ── Historial ─────────────────────────────────────────────────────────────────
def load_history():
    try:
        with open(HISTORY_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_history(entry):
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    hist = load_history()
    hist.insert(0, entry)
    hist = hist[:50]  # máximo 50 entradas
    with open(HISTORY_FILE, "w") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    return hist

# ── Rutas ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    settings = load_settings()
    return render_template("index.html", machines=MACHINES, settings=settings)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "esios": bool(ESIOS_TOKEN), "aemet": bool(AEMET_TOKEN)})

# ── Settings API ─────────────────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())

@app.route("/api/settings", methods=["POST"])
def post_settings():
    data = request.json or {}
    return jsonify(save_settings(data))

# ── Historial API ─────────────────────────────────────────────────────────────
@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify(load_history())

@app.route("/api/history", methods=["POST"])
def post_history():
    entry = request.json or {}
    entry["ts"] = datetime.now(TZ).isoformat()
    return jsonify(save_history(entry))

@app.route("/api/history/<int:idx>", methods=["DELETE"])
def delete_history(idx):
    hist = load_history()
    if 0 <= idx < len(hist):
        hist.pop(idx)
        os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
        with open(HISTORY_FILE, "w") as f:
            json.dump(hist, f, indent=2, ensure_ascii=False)
    return jsonify({"ok": True})

@app.route("/api/history", methods=["DELETE"])
def clear_history():
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        json.dump([], f)
    return jsonify({"ok": True})

# ── ESIOS ─────────────────────────────────────────────────────────────────────
@app.route("/api/prices")
def prices():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Falta date (YYYY-MM-DD)"}), 400
    if not ESIOS_TOKEN:
        return jsonify({"error": "ESIOS_TOKEN no configurado en .env"}), 500
    cached = cache_get(f"prices:{date_str}")
    if cached:
        return jsonify(cached)
    try:
        r = requests.get(f"{ESIOS_BASE}/{ESIOS_INDICATOR}",
            params={"start_date": f"{date_str}T00:00:00+02:00",
                    "end_date":   f"{date_str}T23:59:59+02:00"},
            headers={"Accept": "application/json; application/vnd.esios-api-v1+json",
                     "Content-Type": "application/json",
                     "x-api-key": ESIOS_TOKEN}, timeout=15)
        r.raise_for_status()
        peninsula = [v for v in r.json().get("indicator", {}).get("values", [])
                     if v.get("geo_id") == GEO_PENINSULA]
        if not peninsula:
            return jsonify({"error": f"Sin datos para {date_str} (puede que aún no estén publicados, se publican ~20:30h del día anterior)"}), 404
        ph = {}
        for v in peninsula:
            dt = datetime.fromisoformat(v.get("datetime","").replace("Z","+00:00")).astimezone(TZ)
            ph[dt.hour] = round(v["value"] / 1000, 6)
        result = {"date": date_str, "hours": ph,
                  "avg": round(sum(ph.values())/len(ph), 6),
                  "min": round(min(ph.values()), 6), "max": round(max(ph.values()), 6),
                  "min_h": min(ph, key=ph.get), "max_h": max(ph, key=ph.get)}
        cache_set(f"prices:{date_str}", result, ttl=1800)
        return jsonify(result)
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"ESIOS HTTP {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── AEMET: buscar municipio ───────────────────────────────────────────────────
@app.route("/api/municipios")
def municipios():
    q = request.args.get("q", "").strip().lower()
    if not q or len(q) < 3:
        return jsonify({"error": "Introduce al menos 3 caracteres"}), 400
    if not AEMET_TOKEN:
        return jsonify({"error": "AEMET_TOKEN no configurado"}), 500
    cached = cache_get(f"municipios_list")
    if not cached:
        try:
            r = requests.get(f"{AEMET_BASE}/maestro/municipios",
                headers={"api_key": AEMET_TOKEN, "Accept": "application/json"}, timeout=15)
            r.raise_for_status()
            data_url = r.json().get("datos")
            r2 = requests.get(data_url, timeout=15)
            r2.raise_for_status()
            cached = r2.json()
            cache_set("municipios_list", cached, ttl=86400)  # 24h
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    results = [{"id": m["id"].replace("id",""), "nombre": m["nombre"]}
               for m in cached if q in m.get("nombre","").lower()][:10]
    return jsonify(results)

# ── AEMET: temperatura horaria ───────────────────────────────────────────────
@app.route("/api/temperature")
def temperature():
    date_str  = request.args.get("date")
    settings  = load_settings()
    municipio = request.args.get("municipio", settings["aemet_municipio"])
    if not date_str:
        return jsonify({"error": "Falta date"}), 400
    if not AEMET_TOKEN:
        return jsonify({"error": "AEMET_TOKEN no configurado — añádelo al .env"}), 500
    cached = cache_get(f"temp:{date_str}:{municipio}")
    if cached:
        return jsonify(cached)
    try:
        r1 = requests.get(f"{AEMET_BASE}/prediccion/especifica/municipio/horaria/{municipio}",
            headers={"api_key": AEMET_TOKEN, "Accept": "application/json"}, timeout=15)
        if r1.status_code == 429:
            return jsonify({"error": "AEMET: demasiadas peticiones — espera unos minutos"}), 429
        r1.raise_for_status()
        data_url = r1.json().get("datos")
        if not data_url:
            return jsonify({"error": f"AEMET no devolvió datos para municipio {municipio}. Comprueba el código en ajustes."}), 502
        r2 = requests.get(data_url, timeout=15)
        r2.raise_for_status()
        temps = {}
        for mun in r2.json():
            for dia in mun.get("prediccion", {}).get("dia", []):
                if dia.get("fecha", "").startswith(date_str):
                    for t in dia.get("temperatura", []):
                        try:
                            h = int(t.get("periodo", -1))
                            v = float(t.get("value", 0))
                            if 0 <= h <= 23:
                                temps[h] = v
                        except (ValueError, TypeError):
                            pass
        if not temps:
            return jsonify({"error": f"Sin datos de temperatura para {date_str} (AEMET solo tiene ~48h de predicción horaria)"}), 404
        result = {"date": date_str, "municipio": municipio, "temps": temps,
                  "min": min(temps.values()), "max": max(temps.values())}
        cache_set(f"temp:{date_str}:{municipio}", result, ttl=21600)
        return jsonify(result)
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 429:
            return jsonify({"error": "AEMET: demasiadas peticiones — espera unos minutos"}), 429
        return jsonify({"error": f"AEMET HTTP {code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Prometheus ────────────────────────────────────────────────────────────────
@app.route("/api/prometheus/monthly")
def prometheus_monthly():
    settings = load_settings()
    prom_url = settings.get("prometheus_url", PROMETHEUS_URL)
    try:
        now = datetime.now(TZ)
        r = requests.get(f"{prom_url}/api/v1/query",
            params={"query": "sum_over_time(ac_total_cost_eur_hour[31d]) * (5/60)",
                    "time": now.timestamp()}, timeout=10)
        r.raise_for_status()
        results = r.json().get("data", {}).get("result", [])
        total = sum(float(res["value"][1]) for res in results) if results else 0.0
        r2 = requests.get(f"{prom_url}/api/v1/query",
            params={"query": "ac_cost_accumulated_today_eur"}, timeout=10)
        r2.raise_for_status()
        today_r = r2.json().get("data", {}).get("result", [])
        today = float(today_r[0]["value"][1]) if today_r else 0.0
        r3 = requests.get(f"{prom_url}/api/v1/query",
            params={"query": "ac_pvpc_price_eur_kwh"}, timeout=10)
        r3.raise_for_status()
        price_r = r3.json().get("data", {}).get("result", [])
        price = float(price_r[0]["value"][1]) if price_r else 0.0
        return jsonify({"monthly_eur": round(total, 3), "today_eur": round(today, 3),
                        "pvpc_now": round(price, 6), "month": now.strftime("%B %Y")})
    except Exception as e:
        return jsonify({"error": f"No se pudo conectar a Prometheus: {str(e)}"}), 500

# ── Precios medios semanales (para estimación mensual) ────────────────────────
@app.route("/api/prices/weekly-avg")
def weekly_avg():
    if not ESIOS_TOKEN:
        return jsonify({"error": "ESIOS_TOKEN no configurado"}), 500
    cached = cache_get("weekly_avg")
    if cached:
        return jsonify(cached)
    today = date.today()
    avgs  = {}
    for delta in range(28):
        d = today - timedelta(days=delta+1)
        dow = d.weekday()
        date_str = d.isoformat()
        cached_day = cache_get(f"prices:{date_str}")
        day_prices = cached_day["hours"] if cached_day else None
        if not day_prices:
            try:
                r = requests.get(f"{ESIOS_BASE}/{ESIOS_INDICATOR}",
                    params={"start_date": f"{date_str}T00:00:00+02:00",
                            "end_date":   f"{date_str}T23:59:59+02:00"},
                    headers={"Accept": "application/json; application/vnd.esios-api-v1+json",
                             "Content-Type": "application/json",
                             "x-api-key": ESIOS_TOKEN}, timeout=10)
                if r.status_code == 200:
                    vals = [v for v in r.json().get("indicator",{}).get("values",[])
                            if v.get("geo_id") == GEO_PENINSULA]
                    day_prices = {}
                    for v in vals:
                        dt = datetime.fromisoformat(v.get("datetime","").replace("Z","+00:00")).astimezone(TZ)
                        day_prices[str(dt.hour)] = round(v["value"]/1000, 6)
                    if day_prices:
                        cache_set(f"prices:{date_str}", {"hours": day_prices}, ttl=86400)
            except Exception:
                pass
        if day_prices:
            if dow not in avgs:
                avgs[dow] = {}
            for h, p in day_prices.items():
                if str(h) not in avgs[dow]:
                    avgs[dow][str(h)] = []
                avgs[dow][str(h)].append(float(p))
    result = {dow: {h: round(sum(ps)/len(ps), 6) for h, ps in hours.items()}
              for dow, hours in avgs.items()}
    cache_set("weekly_avg", result, ttl=3600)
    return jsonify(result)

@app.route("/api/machines")
def machines():
    return jsonify(MACHINES)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5656))
    app.run(host="0.0.0.0", port=port, debug=False)
