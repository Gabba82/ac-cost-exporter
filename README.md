# AC Cost Exporter — Grafana/Prometheus

Monitorización del coste del aire acondicionado en tiempo real,
usando precios PVPC de ESIOS (REE) y tu stack Grafana/Prometheus existente.

---

## Máquinas configuradas

| ID interno            | Modelo              | Consumo frío | Consumo calor |
|-----------------------|---------------------|-------------|--------------|
| `mitsubishi_grande`   | MSZ-HR35VF          | 1,21 kW     | 0,975 kW     |
| `mitsubishi_pequena`  | MSZ-HR25VF          | 0,80 kW     | 0,850 kW     |
| `lg_viejita`          | LG AS-H126RKA2      | ~1,30 kW    | ~1,20 kW     |

> La LG es no-inverter (generación antigua), su consumo real puede variar ±10%.

---

## Paso 1 — Token ESIOS

1. Regístrate gratis en https://api.esios.ree.es/  
2. Ve a tu perfil → "Personal token"  
3. Cópialo y ponlo en `.env`:

```bash
cp .env.example .env
# edita .env y rellena ESIOS_TOKEN=tu_token_aqui
```

O expórtalo directamente:
```bash
export ESIOS_TOKEN="tu_token_aqui"
```

---

## Paso 2 — Desplegar el contenedor

```bash
# En onster, en la carpeta del proyecto:
mkdir -p /DATA/AppData/ac-cost-exporter/config
cp schedule.json.example /DATA/AppData/ac-cost-exporter/config/schedule.json

# Lanza el contenedor
docker compose up -d --build

# Comprueba que funciona
curl http://localhost:9212/metrics | grep ac_pvpc
```

---

## Paso 3 — Prometheus

Añade al `prometheus.yml` el bloque de `prometheus-scrape.yml`:

```yaml
scrape_configs:
  # ... tus jobs existentes ...
  - job_name: 'ac-cost-exporter'
    static_configs:
      - targets: ['ac-cost-exporter:9212']
    scrape_interval: 5m
```

Luego reinicia Prometheus:
```bash
docker restart prometheus   # o como lo tengas nombrado
```

---

## Paso 4 — Dashboard Grafana

1. Grafana → Dashboards → Import  
2. Pega el contenido de `grafana-dashboard.json`  
3. Selecciona tu datasource Prometheus → Import

---

## Uso diario — schedule.json

Cada mañana editas `/DATA/AppData/ac-cost-exporter/config/schedule.json`:

```json
{
  "date": "2025-07-15",
  "bono_social_pct": 42.5,
  "machines": {
    "mitsubishi_grande": {
      "active": true,
      "mode": "frio",
      "hours": [9, 10, 11, 14, 15, 16, 17, 18, 19, 20, 21, 22]
    },
    "mitsubishi_pequena": {
      "active": true,
      "mode": "frio",
      "hours": [22, 23]
    },
    "lg_viejita": {
      "active": false,
      "mode": "frio",
      "hours": []
    }
  }
}
```

El exporter recarga el fichero cada 5 minutos automáticamente.  
No hace falta reiniciar el contenedor.

---

## Bono Social

- Edita `bono_social_pct` en el schedule.json  
  - **2025**: `42.5`  
  - **2026** (salvo cambio): `35.0`  
- El descuento se aplica sobre el término de energía (no sobre los peajes)  
- El dashboard muestra la proyección sin bono y con bono para comparar

---

## Opcional — Integración n8n

Puedes automatizar la edición del schedule desde n8n:

1. Crea un webhook HTTP en n8n  
2. El flow escribe el JSON en `/DATA/AppData/ac-cost-exporter/config/schedule.json`  
3. Opcionalmente envíate un Telegram con la proyección del día al publicar el schedule

El exporter ya conecta a la red `observatorio_default`, igual que el resto
de tu stack, así que n8n puede alcanzarlo directamente.

---

## Métricas disponibles

| Métrica | Descripción |
|---|---|
| `ac_pvpc_price_eur_kwh` | Precio PVPC actual €/kWh |
| `ac_pvpc_daily_avg_eur_kwh` | Media del día |
| `ac_pvpc_cheapest_hour` | Hora más barata (0-23) |
| `ac_pvpc_most_expensive_hour` | Hora más cara (0-23) |
| `ac_machine_active{machine,label}` | 1/0 si la máquina está activa |
| `ac_machine_power_kw{machine,label,mode}` | kW consumidos ahora |
| `ac_machine_cost_eur_hour{machine,label}` | €/hora por máquina |
| `ac_total_cost_eur_hour` | €/hora total ahora |
| `ac_total_cost_day_projected_eur` | Proyección del día (€) |
| `ac_cost_accumulated_today_eur` | Acumulado hasta ahora (€) |
| `ac_bono_social_discount_eur_day` | Ahorro Bono Social (€) |
| `ac_total_cost_day_after_bono_eur` | Proyección final con bono (€) |
