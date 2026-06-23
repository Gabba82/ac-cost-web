# ac-cost-web ⚡

App web para calcular el coste del aire acondicionado y otros aparatos con precios PVPC reales de ESIOS (REE), temperatura de AEMET y datos reales de Prometheus.

---

## Funcionalidades

- **Calculadora** — máquinas AC + aparatos extra con sliders de kW, selector de horas por botón o por franjas con fracciones (08:30–13:45), bono social configurable, desglose hora a hora, curva PVPC con temperatura AEMET superpuesta, exportar PDF
- **Comparar días** — dos fechas, mismo uso, coste side-by-side con gráfica comparada
- **Hora óptima** — dado un aparato y una duración, encuentra la ventana de inicio más barata (resolución de 15 min)
- **Estimación mensual** — patrón de uso semanal (horas/día) + precios medios históricos = coste estimado del mes
- **Historial** — guarda los últimos 20 cálculos en el navegador (localStorage)
- **Acumulado real** — conecta con tu Prometheus para ver el coste real acumulado del mes

---

## Instalación en onster

```bash
git clone https://github.com/Gabba82/ac-cost-web.git /DATA/AppData/ac-cost-web
cd /DATA/AppData/ac-cost-web
cp .env.example .env
# Edita .env con tus tokens
nano .env
docker compose up -d --build
```

Abre en el navegador: **http://onster:5656**

---

## Tokens necesarios

| Token | Dónde obtenerlo | Obligatorio |
|-------|----------------|-------------|
| `ESIOS_TOKEN` | https://api.esios.ree.es/ → perfil → Personal token | Sí |
| `AEMET_TOKEN` | https://opendata.aemet.es/centrodedescargas/altaUsuario | Para temperatura |

---

## Actualizar

```bash
cd /DATA/AppData/ac-cost-web
git pull
docker compose up -d --build
```

---

## Bono Social 2026/2027

| Año  | Vulnerable | Vulnerable severo |
|------|-----------|------------------|
| 2026 | 42,5% (prorrogado RDL 16/2025) | 57,5% |
| 2027 | 35% (salvo prórroga) | 50% |

---

## Máquinas configuradas

| Modelo              | Consumo frío | Consumo calor |
|---------------------|-------------|--------------|
| Mitsubishi MSZ-HR35VF | 1,21 kW   | 0,975 kW     |
| Mitsubishi MSZ-HR25VF | 0,80 kW   | 0,850 kW     |
| LG AS-H126RKA2        | ~1,30 kW  | ~1,20 kW     |
