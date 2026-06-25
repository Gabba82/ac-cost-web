#!/usr/bin/env python3
"""
AC Cost Web — servidor Flask
Puerto: 5656
"""

import os, json, re, time, requests
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

TZ              = ZoneInfo("Europe/Madrid")
ESIOS_TOKEN     = os.environ.get("ESIOS_TOKEN", "")
AEMET_TOKEN     = os.environ.get("AEMET_TOKEN", "")
ANTHROPIC_TOKEN = os.environ.get("ANTHROPIC_TOKEN", "")
ESIOS_BASE      = "https://api.esios.ree.es/indicators"
AEMET_BASE      = "https://opendata.aemet.es/opendata/api"
ESIOS_INDICATOR = 1001
GEO_PENINSULA   = 8741

CONFIG_FILE      = os.environ.get("CONFIG_FILE",      "/config/settings.json")
HISTORY_FILE     = os.environ.get("HISTORY_FILE",     "/config/history.json")
CUSTOM_DEV_FILE  = os.environ.get("CUSTOM_DEV_FILE",  "/config/custom_devices.json")

MACHINES = [
    {"id": "mitsubishi_grande",  "label": "Mitsubishi MSZ-HR35VF", "kw_frio": 1.21, "kw_calor": 0.975},
    {"id": "mitsubishi_pequena", "label": "Mitsubishi MSZ-HR25VF",  "kw_frio": 0.80, "kw_calor": 0.850},
    {"id": "lg_viejita",         "label": "LG AS-H126RKA2",          "kw_frio": 1.30, "kw_calor": 1.20},
]

DEFAULT_SETTINGS = {
    "aemet_municipio":        "08200",
    "aemet_municipio_nombre": "Sant Boi de Llobregat",
    "bono_social_pct":        42.5,
    "tarifa_defecto":         "pvpc",
}

# ── Caché ─────────────────────────────────────────────────────────────────────
_cache = {}
def cache_get(key):
    e = _cache.get(key)
    return e["val"] if e and time.time() < e["exp"] else None
def cache_set(key, val, ttl=3600):
    _cache[key] = {"val": val, "exp": time.time() + ttl}

# ── Settings ──────────────────────────────────────────────────────────────────
def load_settings():
    try:
        with open(CONFIG_FILE) as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
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
    hist = hist[:50]
    with open(HISTORY_FILE, "w") as f:
        json.dump(hist, f, indent=2, ensure_ascii=False)
    return hist

# ── Aparatos personalizados ───────────────────────────────────────────────────
def load_custom_devices():
    try:
        with open(CUSTOM_DEV_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save_custom_device(device):
    os.makedirs(os.path.dirname(CUSTOM_DEV_FILE), exist_ok=True)
    devices = load_custom_devices()
    # Actualizar si ya existe el mismo id
    devices = [d for d in devices if d.get("id") != device.get("id")]
    devices.append(device)
    with open(CUSTOM_DEV_FILE, "w") as f:
        json.dump(devices, f, indent=2, ensure_ascii=False)
    return devices

def delete_custom_device(device_id):
    os.makedirs(os.path.dirname(CUSTOM_DEV_FILE), exist_ok=True)
    devices = [d for d in load_custom_devices() if d.get("id") != device_id]
    with open(CUSTOM_DEV_FILE, "w") as f:
        json.dump(devices, f, indent=2, ensure_ascii=False)
    return devices

# ── Rutas ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    settings       = load_settings()
    custom_devices = load_custom_devices()
    return render_template("index.html", machines=MACHINES,
                           settings=settings, custom_devices=custom_devices)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "esios": bool(ESIOS_TOKEN),
                    "aemet": bool(AEMET_TOKEN), "ai": bool(ANTHROPIC_TOKEN)})

# ── Settings API ──────────────────────────────────────────────────────────────
@app.route("/api/settings", methods=["GET"])
def get_settings():
    return jsonify(load_settings())

@app.route("/api/settings", methods=["POST"])
def post_settings():
    return jsonify(save_settings(request.json or {}))

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
def delete_history_entry(idx):
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

# ── Aparatos personalizados API ───────────────────────────────────────────────
@app.route("/api/custom-devices", methods=["GET"])
def get_custom_devices():
    return jsonify(load_custom_devices())

@app.route("/api/custom-devices", methods=["POST"])
def post_custom_device():
    device = request.json or {}
    if not device.get("id") or not device.get("label"):
        return jsonify({"error": "Faltan campos id y label"}), 400
    return jsonify(save_custom_device(device))

@app.route("/api/custom-devices/<device_id>", methods=["DELETE"])
def del_custom_device(device_id):
    return jsonify(delete_custom_device(device_id))

# ── IA: buscar consumo de aparato ─────────────────────────────────────────────
@app.route("/api/search-consumption")
def search_consumption():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"error": "Falta el parámetro q"}), 400
    if not ANTHROPIC_TOKEN:
        return jsonify({"error": "ANTHROPIC_TOKEN no configurado"}), 500

    cached = cache_get(f"consumption:{query.lower()}")
    if cached:
        return jsonify(cached)

    prompt = f"""Eres un experto en eficiencia energética. El usuario quiere saber el consumo eléctrico típico de este aparato: "{query}".

Responde ÚNICAMENTE con un JSON válido, sin texto adicional, sin bloques de código, sin explicaciones:
{{
  "label": "nombre normalizado del aparato en español",
  "kw_min": número decimal (consumo mínimo en kW),
  "kw_max": número decimal (consumo máximo en kW),
  "kw_tipico": número decimal (consumo típico/recomendado en kW),
  "nota": "una frase breve explicando el rango o el modo de uso típico"
}}

Ejemplos de valores correctos:
- Televisor 55" OLED: kw_min=0.05, kw_max=0.15, kw_tipico=0.10
- Lavadora ciclo normal: kw_min=0.5, kw_max=2.5, kw_tipico=1.0
- Horno eléctrico: kw_min=1.0, kw_max=3.5, kw_tipico=2.2

Si no reconoces el aparato, devuelve kw_tipico=null y nota explicando que no tienes datos."""

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_TOKEN,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 300,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=20,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip()
        # Limpiar bloques markdown ```json ... ``` si Claude los incluye
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"```$", "", text).strip()
        result = json.loads(text)
        cache_set(f"consumption:{query.lower()}", result, ttl=86400)
        return jsonify(result)
    except json.JSONDecodeError:
        return jsonify({"error": "La IA no devolvió JSON válido", "raw": text[:200]}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── ESIOS: precios ────────────────────────────────────────────────────────────
def _fetch_esios(date_str):
    cached = cache_get(f"prices:{date_str}")
    if cached:
        return cached
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
        return None
    ph = {}
    for v in peninsula:
        dt = datetime.fromisoformat(v.get("datetime","").replace("Z","+00:00")).astimezone(TZ)
        ph[dt.hour] = round(v["value"] / 1000, 6)
    result = {"date": date_str, "hours": ph,
              "avg": round(sum(ph.values())/len(ph), 6),
              "min": round(min(ph.values()), 6), "max": round(max(ph.values()), 6),
              "min_h": min(ph, key=ph.get), "max_h": max(ph, key=ph.get)}
    ttl = 1800 if date_str == date.today().isoformat() else 86400
    cache_set(f"prices:{date_str}", result, ttl=ttl)
    return result

@app.route("/api/prices")
def prices():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Falta date (YYYY-MM-DD)"}), 400
    if not ESIOS_TOKEN:
        return jsonify({"error": "ESIOS_TOKEN no configurado en .env"}), 500
    try:
        result = _fetch_esios(date_str)
        if not result:
            return jsonify({"error": f"Sin datos para {date_str} (se publican ~20:30h del día anterior)"}), 404
        return jsonify(result)
    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"ESIOS HTTP {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── ESIOS: histórico 30 días ──────────────────────────────────────────────────
@app.route("/api/prices/history")
def prices_history():
    if not ESIOS_TOKEN:
        return jsonify({"error": "ESIOS_TOKEN no configurado"}), 500
    cached = cache_get("prices_history_30d")
    if cached:
        return jsonify(cached)
    today = date.today()
    result = {}
    for delta in range(30):
        d = today - timedelta(days=delta)
        date_str = d.isoformat()
        try:
            data = _fetch_esios(date_str)
            if data:
                result[date_str] = {"avg": data["avg"], "min": data["min"], "max": data["max"]}
        except Exception:
            pass
    cache_set("prices_history_30d", result, ttl=3600)
    return jsonify(result)

# ── AEMET: municipios ─────────────────────────────────────────────────────────
@app.route("/api/municipios")
def municipios():
    q = request.args.get("q", "").strip().lower()
    if not q or len(q) < 3:
        return jsonify({"error": "Introduce al menos 3 caracteres"}), 400
    if not AEMET_TOKEN:
        return jsonify({"error": "AEMET_TOKEN no configurado"}), 500
    cached = cache_get("municipios_list")
    if not cached:
        try:
            r = requests.get(f"{AEMET_BASE}/maestro/municipios",
                headers={"api_key": AEMET_TOKEN, "Accept": "application/json"}, timeout=15)
            r.raise_for_status()
            r2 = requests.get(r.json().get("datos"), timeout=15)
            r2.raise_for_status()
            cached = r2.json()
            cache_set("municipios_list", cached, ttl=86400)
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    results = [{"id": m["id"].replace("id",""), "nombre": m["nombre"]}
               for m in cached if q in m.get("nombre","").lower()][:10]
    return jsonify(results)

# ── AEMET: temperatura horaria ────────────────────────────────────────────────
@app.route("/api/temperature")
def temperature():
    date_str  = request.args.get("date")
    settings  = load_settings()
    municipio = request.args.get("municipio", settings["aemet_municipio"])
    if not date_str:
        return jsonify({"error": "Falta date"}), 400
    if not AEMET_TOKEN:
        return jsonify({"error": "AEMET_TOKEN no configurado"}), 500
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
            return jsonify({"error": f"AEMET no devolvió datos para municipio {municipio}"}), 502
        r2 = requests.get(data_url, timeout=15)
        r2.raise_for_status()
        prediccion = json.loads(r2.content.decode("latin-1"))
        temps = {}
        for mun in prediccion:
            for dia in mun.get("prediccion", {}).get("dia", []):
                if dia.get("fecha", "")[:10] != date_str:
                    continue
                for t in dia.get("temperatura", []):
                    try:
                        periodo = str(t.get("periodo", "")).strip()
                        if len(periodo) == 2 and periodo.isdigit():
                            h = int(periodo)
                            if 0 <= h <= 23:
                                temps[h] = float(t.get("value", 0))
                    except (ValueError, TypeError):
                        pass
        if not temps:
            return jsonify({"error": "AEMET solo publica horas futuras para hoy. Prueba mañana."}), 404
        result = {"date": date_str, "municipio": municipio, "temps": temps,
                  "min": min(temps.values()), "max": max(temps.values())}
        cache_set(f"temp:{date_str}:{municipio}", result, ttl=21600)
        return jsonify(result)
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code
        if code == 429:
            return jsonify({"error": "AEMET: demasiadas peticiones"}), 429
        return jsonify({"error": f"AEMET HTTP {code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Precios medios semanales ──────────────────────────────────────────────────
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
        try:
            data = _fetch_esios(d.isoformat())
            if data:
                if dow not in avgs:
                    avgs[dow] = {}
                for h, p in data["hours"].items():
                    k = str(h)
                    if k not in avgs[dow]:
                        avgs[dow][k] = []
                    avgs[dow][k].append(float(p))
        except Exception:
            pass
    result = {dow: {h: round(sum(ps)/len(ps), 6) for h, ps in hours.items()}
              for dow, hours in avgs.items()}
    cache_set("weekly_avg", result, ttl=3600)
    return jsonify(result)

@app.route("/api/machines")
def machines_route():
    return jsonify(MACHINES)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5656))
    app.run(host="0.0.0.0", port=port, debug=False)
