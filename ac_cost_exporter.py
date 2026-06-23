#!/usr/bin/env python3
"""
AC Cost Exporter para Prometheus
Consulta ESIOS API (precio PVPC hora a hora) y calcula el coste estimado
del aire acondicionado según las máquinas activas configuradas.

Puerto: 9212
"""

import os
import json
import time
import logging
import requests
from datetime import datetime, date
from prometheus_client import start_http_server, Gauge
from zoneinfo import ZoneInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ac-cost-exporter")

TZ = ZoneInfo("Europe/Madrid")

# ESIOS devuelve múltiples filas por hora (una por zona geográfica).
# Filtramos solo la Península (geo_id 8741).
ESIOS_GEO_PENINSULA = 8741
ESIOS_INDICATORS    = [1001]   # 1001 = PVPC T. 2.0TD (€/MWh)
ESIOS_BASE          = "https://api.esios.ree.es/indicators"

def esios_headers():
    return {
        "Accept":       "application/json; application/vnd.esios-api-v1+json",
        "Content-Type": "application/json",
        "x-api-key":    ESIOS_TOKEN,
    }

ESIOS_TOKEN     = os.environ.get("ESIOS_TOKEN", "")
CONFIG_FILE     = os.environ.get("CONFIG_FILE", "/config/schedule.json")
BONO_SOCIAL_PCT = float(os.environ.get("BONO_SOCIAL_PCT", "42.5"))

# ─── Máquinas ─────────────────────────────────────────────────────────────────
MACHINES = {
    "mitsubishi_grande": {
        "label":    "Mitsubishi MSZ-HR35VF",
        "kw_frio":  1.21,
        "kw_calor": 0.975,
    },
    "mitsubishi_pequena": {
        "label":    "Mitsubishi MSZ-HR25VF",
        "kw_frio":  0.80,
        "kw_calor": 0.850,
    },
    "lg_viejita": {
        "label":    "LG AS-H126RKA2",
        "kw_frio":  1.30,
        "kw_calor": 1.20,
    },
}

# ─── Métricas Prometheus ──────────────────────────────────────────────────────
pvpc_price_eur_kwh       = Gauge("ac_pvpc_price_eur_kwh",          "Precio PVPC actual €/kWh")
pvpc_price_hour          = Gauge("ac_pvpc_price_hour",              "Hora del precio PVPC (0-23)")
pvpc_daily_avg           = Gauge("ac_pvpc_daily_avg_eur_kwh",       "Precio medio PVPC del día")
pvpc_cheapest_hour       = Gauge("ac_pvpc_cheapest_hour",           "Hora más barata (0-23)")
pvpc_most_expensive_hour = Gauge("ac_pvpc_most_expensive_hour",     "Hora más cara (0-23)")
machine_active           = Gauge("ac_machine_active",               "1 si activa", ["machine", "label"])
machine_power_kw         = Gauge("ac_machine_power_kw",             "Potencia kW", ["machine", "label", "mode"])
machine_cost_eur_hour    = Gauge("ac_machine_cost_eur_hour",        "€/hora por máquina", ["machine", "label"])
total_cost_eur_hour      = Gauge("ac_total_cost_eur_hour",          "€/hora total ahora")
total_cost_day_projected = Gauge("ac_total_cost_day_projected_eur", "Proyección día (€)")
cost_accumulated_today   = Gauge("ac_cost_accumulated_today_eur",   "Acumulado hoy (€)")
bono_discount_eur_day    = Gauge("ac_bono_social_discount_eur_day", "Ahorro Bono Social (€)")
total_cost_after_bono    = Gauge("ac_total_cost_day_after_bono_eur","Proyección con bono (€)")

# ─── Caché de precios ─────────────────────────────────────────────────────────
_price_cache: dict[int, float] = {}
_cache_date: date | None = None


def fetch_pvpc_prices(target_date: date) -> dict[int, float]:
    """
    Descarga los precios PVPC de ESIOS para target_date.
    Filtra solo geo_id 8741 (Península) para evitar duplicados por zona.
    Los valores vienen en €/MWh → se convierten a €/kWh.
    """
    start = datetime(target_date.year, target_date.month, target_date.day,
                     0, 0, 0, tzinfo=TZ).isoformat()
    end   = datetime(target_date.year, target_date.month, target_date.day,
                     23, 59, 59, tzinfo=TZ).isoformat()

    for indicator in ESIOS_INDICATORS:
        url    = f"{ESIOS_BASE}/{indicator}"
        params = {"start_date": start, "end_date": end}
        try:
            r = requests.get(url, headers=esios_headers(), params=params, timeout=15)
            log.info(f"ESIOS indicator {indicator} → HTTP {r.status_code}")

            if r.status_code in (401, 403):
                log.error(f"ESIOS: HTTP {r.status_code} — comprueba que ESIOS_TOKEN es válido y está definido en .env")
                continue

            r.raise_for_status()
            values = r.json().get("indicator", {}).get("values", [])
            log.info(f"ESIOS: {len(values)} filas totales (incluye todas las zonas geográficas)")

            # Filtrar solo Península (geo_id 8741)
            peninsula = [v for v in values if v.get("geo_id") == ESIOS_GEO_PENINSULA]
            log.info(f"ESIOS: {len(peninsula)} filas Península")

            if not peninsula:
                log.warning("Sin datos para Península — puede que los precios de mañana aún no estén publicados")
                continue

            prices: dict[int, float] = {}
            for v in peninsula:
                raw_dt   = (v.get("datetime") or v.get("datetime_utc", "")).replace("Z", "+00:00")
                dt_local = datetime.fromisoformat(raw_dt).astimezone(TZ)
                hora     = dt_local.hour
                prices[hora] = round(v["value"] / 1000.0, 6)  # €/MWh → €/kWh

            log.info(
                f"PVPC {target_date} | {len(prices)} horas | "
                f"min={min(prices.values()):.4f} max={max(prices.values()):.4f} €/kWh"
            )
            return prices

        except Exception as e:
            log.error(f"Error con indicador {indicator}: {e}")

    log.error("No se pudieron obtener precios de ESIOS")
    return {}


def get_prices(target_date: date) -> dict[int, float]:
    global _price_cache, _cache_date
    if _cache_date != target_date:
        _price_cache = fetch_pvpc_prices(target_date)
        _cache_date  = target_date
    return _price_cache


def load_schedule() -> dict:
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        log.warning(f"schedule.json no encontrado en {CONFIG_FILE}, usando schedule vacío")
        return {"machines": {m: {"active": False, "mode": "frio", "hours": []} for m in MACHINES}}
    except Exception as e:
        log.error(f"Error leyendo schedule.json: {e}")
        return {"machines": {m: {"active": False, "mode": "frio", "hours": []} for m in MACHINES}}


def update_metrics():
    now         = datetime.now(TZ)
    today       = now.date()
    hora_actual = now.hour
    prices      = get_prices(today)
    schedule    = load_schedule()
    bono_pct    = schedule.get("bono_social_pct", BONO_SOCIAL_PCT)

    precio_actual = prices.get(hora_actual, 0.0)
    pvpc_price_eur_kwh.set(precio_actual)
    pvpc_price_hour.set(hora_actual)

    if prices:
        avg   = sum(prices.values()) / len(prices)
        cheap = min(prices, key=prices.get)
        expen = max(prices, key=prices.get)
        pvpc_daily_avg.set(avg)
        pvpc_cheapest_hour.set(cheap)
        pvpc_most_expensive_hour.set(expen)
    else:
        avg = 0.0

    total_kw_now   = 0.0
    total_cost_now = 0.0
    total_proj     = 0.0
    total_accum    = 0.0

    for machine_id, specs in MACHINES.items():
        sched     = schedule.get("machines", {}).get(machine_id, {})
        is_active = sched.get("active", False)
        mode      = sched.get("mode", "frio")
        hours     = sched.get("hours", [])
        lbl       = specs["label"]
        kw        = specs[f"kw_{mode}"]

        machine_active.labels(machine=machine_id, label=lbl).set(1 if is_active else 0)

        if is_active:
            machine_power_kw.labels(machine=machine_id, label=lbl, mode=mode).set(kw)
            cost_h = kw * precio_actual
            machine_cost_eur_hour.labels(machine=machine_id, label=lbl).set(cost_h)
            if hora_actual in hours:
                total_kw_now   += kw
                total_cost_now += cost_h
            for h in hours:
                total_proj  += kw * prices.get(h, avg)
            for h in hours:
                if h < hora_actual:
                    total_accum += kw * prices.get(h, avg)
        else:
            machine_power_kw.labels(machine=machine_id, label=lbl, mode=mode).set(0)
            machine_cost_eur_hour.labels(machine=machine_id, label=lbl).set(0)

    descuento = total_proj * (bono_pct / 100.0)
    total_cost_eur_hour.set(total_cost_now)
    total_cost_day_projected.set(total_proj)
    cost_accumulated_today.set(total_accum)
    bono_discount_eur_day.set(descuento)
    total_cost_after_bono.set(total_proj - descuento)

    log.info(
        f"[{now.strftime('%H:%M')}] "
        f"PVPC={precio_actual:.4f}€/kWh | "
        f"Activo={total_kw_now:.2f}kW ({total_cost_now:.4f}€/h) | "
        f"Proyección={total_proj:.3f}€ | "
        f"Con bono({bono_pct}%)={total_proj - descuento:.3f}€"
    )


def main():
    port = int(os.environ.get("EXPORTER_PORT", "9212"))
    log.info(f"Iniciando AC Cost Exporter en puerto {port}")
    start_http_server(port)

    if not ESIOS_TOKEN:
        log.warning("⚠️  ESIOS_TOKEN no definido — comprueba que .env contiene: ESIOS_TOKEN=tu_token")
    else:
        log.info(f"✅ ESIOS_TOKEN cargado ({ESIOS_TOKEN[:8]}...)")

    while True:
        update_metrics()
        time.sleep(300)


if __name__ == "__main__":
    main()
