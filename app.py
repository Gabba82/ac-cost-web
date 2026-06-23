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
AEMET_MUNICIPIO = os.environ.get("AEMET_MUNICIPIO", "08019")  # Barcelona por defecto
PROMETHEUS_URL  = os.environ.get("PROMETHEUS_URL", "http://observatorio-prometheus:9090")

MACHINES = [
    {"id": "mitsubishi_grande",  "label": "Mitsubishi MSZ-HR35VF", "kw_frio": 1.21, "kw_calor": 0.975},
    {"id": "mitsubishi_pequena", "label": "Mitsubishi MSZ-HR25VF",  "kw_frio": 0.80, "kw_calor": 0.850},
    {"id": "lg_viejita",         "label": "LG AS-H126RKA2",          "kw_frio": 1.30, "kw_calor": 1.20},
]

# ── Caché simple en memoria ──────────────────────────────────────────────────
_cache = {}

def cache_get(key):
    entry = _cache.get(key)
    if entry and time.time() < entry["exp"]:
        return entry["val"]
    return None

def cache_set(key, val, ttl=3600):
    _cache[key] = {"val": val, "exp": time.time() + ttl}


# ── Rutas principales ────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", machines=MACHINES)

@app.route("/health")
def health():
    return jsonify({"status": "ok", "esios": bool(ESIOS_TOKEN), "aemet": bool(AEMET_TOKEN)})


# ── ESIOS: precios PVPC ──────────────────────────────────────────────────────
@app.route("/api/prices")
def prices():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Falta date (YYYY-MM-DD)"}), 400
    if not ESIOS_TOKEN:
        return jsonify({"error": "ESIOS_TOKEN no configurado"}), 500

    cached = cache_get(f"prices:{date_str}")
    if cached:
        return jsonify(cached)

    try:
        start = f"{date_str}T00:00:00+02:00"
        end   = f"{date_str}T23:59:59+02:00"
        r = requests.get(f"{ESIOS_BASE}/{ESIOS_INDICATOR}",
                         params={"start_date": start, "end_date": end},
                         headers={"Accept": "application/json; application/vnd.esios-api-v1+json",
                                  "Content-Type": "application/json",
                                  "x-api-key": ESIOS_TOKEN}, timeout=15)
        r.raise_for_status()
        values = r.json().get("indicator", {}).get("values", [])
        peninsula = [v for v in values if v.get("geo_id") == GEO_PENINSULA]
        if not peninsula:
            return jsonify({"error": f"Sin datos para {date_str}"}), 404

        prices_by_hour = {}
        for v in peninsula:
            raw = v.get("datetime", v.get("datetime_utc", "")).replace("Z", "+00:00")
            dt  = datetime.fromisoformat(raw).astimezone(TZ)
            prices_by_hour[dt.hour] = round(v["value"] / 1000, 6)

        result = {
            "date":  date_str,
            "hours": prices_by_hour,
            "avg":   round(sum(prices_by_hour.values()) / len(prices_by_hour), 6),
            "min":   round(min(prices_by_hour.values()), 6),
            "max":   round(max(prices_by_hour.values()), 6),
            "min_h": min(prices_by_hour, key=prices_by_hour.get),
            "max_h": max(prices_by_hour, key=prices_by_hour.get),
        }
        cache_set(f"prices:{date_str}", result, ttl=1800)
        return jsonify(result)

    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"ESIOS HTTP {e.response.status_code}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── AEMET: temperatura horaria ───────────────────────────────────────────────
@app.route("/api/temperature")
def temperature():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Falta date"}), 400
    if not AEMET_TOKEN:
        return jsonify({"error": "AEMET_TOKEN no configurado — añádelo al .env"}), 500

    cached = cache_get(f"temp:{date_str}")
    if cached:
        return jsonify(cached)

    try:
        # Paso 1: AEMET devuelve una URL de datos en la primera llamada
        r1 = requests.get(
            f"{AEMET_BASE}/prediccion/especifica/municipio/horaria/{AEMET_MUNICIPIO}",
            headers={"api_key": AEMET_TOKEN, "Accept": "application/json"},
            timeout=15)
        r1.raise_for_status()
        data_url = r1.json().get("datos")
        if not data_url:
            return jsonify({"error": "AEMET no devolvió URL de datos"}), 502

        # Paso 2: obtener los datos reales
        r2 = requests.get(data_url, timeout=15)
        r2.raise_for_status()
        prediccion = r2.json()

        # Extraer temperaturas horarias para la fecha solicitada
        temps = {}
        for municipio in prediccion:
            for dia in municipio.get("prediccion", {}).get("dia", []):
                if dia.get("fecha", "").startswith(date_str):
                    for t in dia.get("temperatura", []):
                        try:
                            hora  = int(t.get("periodo", -1))
                            valor = float(t.get("value", 0))
                            if 0 <= hora <= 23:
                                temps[hora] = valor
                        except (ValueError, TypeError):
                            pass

        if not temps:
            return jsonify({"error": f"Sin datos de temperatura para {date_str} (AEMET solo tiene ~48h de predicción horaria)"}), 404

        result = {"date": date_str, "temps": temps,
                  "min": min(temps.values()), "max": max(temps.values())}
        cache_set(f"temp:{date_str}", result, ttl=3600)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Prometheus: acumulado real del mes ──────────────────────────────────────
@app.route("/api/prometheus/monthly")
def prometheus_monthly():
    try:
        now   = datetime.now(TZ)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Query: suma del coste acumulado (usando increase sobre ac_cost_accumulated_today_eur)
        # Usamos ac_total_cost_eur_hour integrado en el tiempo
        query = 'sum_over_time(ac_total_cost_eur_hour[31d]) * (5/60)'
        r = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                         params={"query": query, "time": now.timestamp()},
                         timeout=10)
        r.raise_for_status()
        data = r.json()
        results = data.get("data", {}).get("result", [])
        total = sum(float(res["value"][1]) for res in results) if results else 0.0

        # También pedimos el acumulado de hoy
        r2 = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                          params={"query": "ac_cost_accumulated_today_eur"},
                          timeout=10)
        r2.raise_for_status()
        today_results = r2.json().get("data", {}).get("result", [])
        today = float(today_results[0]["value"][1]) if today_results else 0.0

        return jsonify({"monthly_eur": round(total, 3), "today_eur": round(today, 3),
                        "month": now.strftime("%B %Y")})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── ESIOS histórico: precios medios por día de semana (para estimación mensual)
@app.route("/api/prices/weekly-avg")
def weekly_avg():
    """Devuelve el precio medio por hora de los últimos 30 días agrupado por día de semana."""
    try:
        if not ESIOS_TOKEN:
            return jsonify({"error": "ESIOS_TOKEN no configurado"}), 500

        cached = cache_get("weekly_avg")
        if cached:
            return jsonify(cached)

        today = date.today()
        avgs  = {}  # día_semana(0=lun) → {hora → [precios]}

        for delta in range(28):  # 4 semanas
            d = today - timedelta(days=delta+1)
            dow = d.weekday()
            date_str = d.isoformat()

            cached_day = cache_get(f"prices:{date_str}")
            day_prices = cached_day["hours"] if cached_day else None

            if not day_prices:
                try:
                    start = f"{date_str}T00:00:00+02:00"
                    end   = f"{date_str}T23:59:59+02:00"
                    r = requests.get(f"{ESIOS_BASE}/{ESIOS_INDICATOR}",
                                     params={"start_date": start, "end_date": end},
                                     headers={"Accept": "application/json; application/vnd.esios-api-v1+json",
                                              "Content-Type": "application/json",
                                              "x-api-key": ESIOS_TOKEN}, timeout=10)
                    if r.status_code == 200:
                        vals = r.json().get("indicator", {}).get("values", [])
                        day_prices = {}
                        for v in [v for v in vals if v.get("geo_id") == GEO_PENINSULA]:
                            raw = v.get("datetime", "").replace("Z", "+00:00")
                            dt  = datetime.fromisoformat(raw).astimezone(TZ)
                            day_prices[str(dt.hour)] = round(v["value"] / 1000, 6)
                        if day_prices:
                            cache_set(f"prices:{date_str}", {"hours": day_prices}, ttl=86400)
                except Exception:
                    pass

            if day_prices:
                if dow not in avgs:
                    avgs[dow] = {}
                for h, p in day_prices.items():
                    h = str(h)
                    if h not in avgs[dow]:
                        avgs[dow][h] = []
                    avgs[dow][h].append(float(p))

        # Calcular medias
        result = {}
        for dow, hours in avgs.items():
            result[dow] = {h: round(sum(ps)/len(ps), 6) for h, ps in hours.items()}

        cache_set("weekly_avg", result, ttl=3600)
        return jsonify(result)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/machines")
def machines():
    return jsonify(MACHINES)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5656))
    app.run(host="0.0.0.0", port=port, debug=False)
