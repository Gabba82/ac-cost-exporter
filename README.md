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

## Instalación

### Requisitos previos

- Docker y Docker Compose instalados
- Red Docker `observatorio_default` existente (la del stack Grafana/Prometheus)
- Token de ESIOS gratuito → regístrate en https://api.esios.ree.es/ → perfil → "Personal token"

---

### 1 — Clonar el repositorio

```bash
git clone https://github.com/Gabba82/ac-cost-exporter.git /DATA/AppData/ac-cost-exporter
cd /DATA/AppData/ac-cost-exporter
```

---

### 2 — Configurar el token de ESIOS

Crea el fichero `.env` en la raíz del proyecto:

```bash
echo "ESIOS_TOKEN=tu_token_aqui" > .env
```

> ⚠️ El `.gitignore` ya excluye `.env` para que el token nunca se suba al repo.

---

### 3 — Crear el schedule del día

```bash
mkdir -p config
cp schedule.json.example config/schedule.json
```

Edita `config/schedule.json` para indicar qué máquinas enciendes y en qué horas (ver sección [Uso diario](#uso-diario--schedulejson)).

---

### 4 — Arrancar el contenedor

```bash
docker compose up -d --build
```

Verifica que el exporter está publicando métricas:

```bash
curl http://localhost:9212/metrics | grep ac_pvpc
```

Deberías ver algo como:
```
ac_pvpc_price_eur_kwh 0.1423
ac_pvpc_daily_avg_eur_kwh 0.1187
...
```

---

### 5 — Añadir a Prometheus

Edita tu `prometheus.yml` y añade el job (también disponible en `prometheus-scrape.yml`):

```yaml
scrape_configs:
  # ... tus jobs existentes ...
  - job_name: 'ac-cost-exporter'
    static_configs:
      - targets: ['ac-cost-exporter:9212']
    scrape_interval: 5m
```

Reinicia Prometheus para que cargue la nueva configuración:

```bash
docker restart prometheus   # ajusta el nombre si es distinto
```

---

### 6 — Importar el dashboard en Grafana

1. Grafana → Dashboards → **Import**
2. Pega el contenido de `grafana-dashboard.json` (o sube el fichero directamente)
3. Selecciona tu datasource Prometheus → **Import**

---

### Actualizar a la última versión

```bash
cd /DATA/AppData/ac-cost-exporter
git pull
docker compose up -d --build
```

---

## Uso diario — schedule.json

Cada mañana editas `config/schedule.json` para planificar el uso del aire ese día:

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

El exporter recarga el fichero cada 5 minutos automáticamente — no hace falta reiniciar el contenedor.

---

## Bono Social

Edita `bono_social_pct` en el `schedule.json` según el año:

| Año  | Vulnerable | Vulnerable severo | Estado |
|------|-----------|------------------|--------|
| 2025 | 42,5%     | 57,5%            | Finalizado |
| 2026 | **42,5%** | **57,5%**        | ✅ Vigente (RDL 16/2025 + RDL 2/2026) |
| 2027 | 35%       | 50%              | Salvo prórroga |

> El descuento se aplica sobre el término de energía del PVPC (no sobre peajes ni impuestos).
> El dashboard muestra siempre la proyección sin bono y con bono para comparar.

---

## Opcional — Integración n8n

Puedes automatizar la edición del schedule desde n8n:

1. Crea un webhook HTTP en n8n
2. El flow escribe el JSON en `config/schedule.json`
3. Opcionalmente envíate un Telegram con la proyección del día

El exporter ya conecta a la red `observatorio_default`, igual que el resto de tu stack, así que n8n puede alcanzarlo directamente.

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
