#!/usr/bin/env python3
"""
AC Cost Web — servidor Flask
Actúa de proxy entre el browser y ESIOS para no exponer el token.
Puerto: 5656
"""

import os
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)

TZ              = ZoneInfo("Europe/Madrid")
ESIOS_TOKEN     = os.environ.get("ESIOS_TOKEN", "")
ESIOS_BASE      = "https://api.esios.ree.es/indicators"
ESIOS_INDICATOR = 1001
GEO_PENINSULA   = 8741

MACHINES = [
    {"id": "mitsubishi_grande",  "label": "Mitsubishi MSZ-HR35VF", "kw_frio": 1.21, "kw_calor": 0.975},
    {"id": "mitsubishi_pequena", "label": "Mitsubishi MSZ-HR25VF",  "kw_frio": 0.80, "kw_calor": 0.850},
    {"id": "lg_viejita",         "label": "LG AS-H126RKA2",          "kw_frio": 1.30, "kw_calor": 1.20},
]


@app.route("/")
def index():
    return render_template("index.html", machines=MACHINES)


@app.route("/api/prices")
def prices():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Falta el parámetro date (YYYY-MM-DD)"}), 400

    if not ESIOS_TOKEN:
        return jsonify({"error": "ESIOS_TOKEN no configurado en el servidor"}), 500

    try:
        start = f"{date_str}T00:00:00+02:00"
        end   = f"{date_str}T23:59:59+02:00"
        url   = f"{ESIOS_BASE}/{ESIOS_INDICATOR}"
        r = requests.get(url, params={"start_date": start, "end_date": end},
                         headers={
                             "Accept":       "application/json; application/vnd.esios-api-v1+json",
                             "Content-Type": "application/json",
                             "x-api-key":    ESIOS_TOKEN,
                         }, timeout=15)
        r.raise_for_status()

        values = r.json().get("indicator", {}).get("values", [])
        peninsula = [v for v in values if v.get("geo_id") == GEO_PENINSULA]

        if not peninsula:
            return jsonify({"error": f"Sin datos para {date_str} — puede que aún no estén publicados (se publican ~20:30h del día anterior)"}), 404

        prices_by_hour = {}
        for v in peninsula:
            raw = v.get("datetime", v.get("datetime_utc", "")).replace("Z", "+00:00")
            dt  = datetime.fromisoformat(raw).astimezone(TZ)
            prices_by_hour[dt.hour] = round(v["value"] / 1000, 6)  # €/MWh → €/kWh

        return jsonify({
            "date":   date_str,
            "hours":  prices_by_hour,
            "avg":    round(sum(prices_by_hour.values()) / len(prices_by_hour), 6),
            "min":    round(min(prices_by_hour.values()), 6),
            "max":    round(max(prices_by_hour.values()), 6),
            "min_h":  min(prices_by_hour, key=prices_by_hour.get),
            "max_h":  max(prices_by_hour, key=prices_by_hour.get),
        })

    except requests.exceptions.HTTPError as e:
        return jsonify({"error": f"ESIOS HTTP {e.response.status_code} — comprueba el token"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/machines")
def machines():
    return jsonify(MACHINES)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "token_configured": bool(ESIOS_TOKEN)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5656))
    app.run(host="0.0.0.0", port=port, debug=False)
