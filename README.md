# ac-cost-web ⚡

App web para calcular el coste del aire acondicionado con precios PVPC reales de ESIOS (REE).

El token de ESIOS se queda en el servidor — nunca llega al navegador.

---

## Instalación en onster

```bash
git clone https://github.com/Gabba82/ac-cost-web.git /DATA/AppData/ac-cost-web
cd /DATA/AppData/ac-cost-web

# Token ESIOS (regístrate gratis en https://api.esios.ree.es/)
echo "ESIOS_TOKEN=tu_token_aqui" > .env

docker compose up -d --build
```

Abre en el navegador: **http://onster:5656** (o la IP de tu máquina)

---

## Actualizar

```bash
cd /DATA/AppData/ac-cost-web
git pull
docker compose up -d --build
```

---

## Uso

1. Selecciona la fecha (los precios del día siguiente se publican ~20:30h)
2. Pulsa **Cargar precios**
3. Activa las máquinas que vayas a encender y elige frío/calor
4. Selecciona las horas de uso (o usa "3 más baratas" para optimizar)
5. Elige tu descuento de Bono Social si aplica

### Bono Social 2026/2027

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
