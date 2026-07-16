# ac-cost-web — contexto del proyecto

App Flask de una sola página para calcular el coste eléctrico (aire acondicionado
y otros aparatos) con precios PVPC reales de ESIOS/REE y temperatura de AEMET.
Repo público: `github.com/Gabba82/ac-cost-web`.

## Arquitectura

- **Backend**: `app.py` — Flask monolítico, sin blueprints. Todas las rutas API
  en un único fichero.
- **Frontend**: `templates/index.html` — una sola plantilla Jinja con todo el
  CSS y JS inline (sin build step, sin npm). Vanilla JS, sin framework.
  Chart.js por CDN para las gráficas.
- **Persistencia**: ficheros JSON en `/config` (montado como volumen Docker):
  `settings.json`, `history.json`, `custom_devices.json`. No hay base de datos.
- **Despliegue**: Docker (`Dockerfile` + `docker-compose.yml`), gunicorn en
  producción, puerto 5656.

## Entorno de trabajo — importante

El checkout local de Windows (`c:/DATA/AppData/ac-cost-web`) **no es** el
servidor de producción. El servidor real es `onster` (Linux, ruta
`/DATA/AppData/ac-cost-web`). El flujo de despliegue es siempre:

```bash
# En local: commit + push
git add ... && git commit -m "..." && git push origin main

# En onster (por SSH, el usuario lo ejecuta):
cd /DATA/AppData/ac-cost-web
git pull
docker compose up -d --build
```

No asumas que un cambio está desplegado solo porque está en el repo — hay que
confirmar que se ha hecho `git pull` + rebuild en el servidor. El `config/`
vive en un volumen aparte, así que un rebuild no pierde settings/historial.

## Tokens necesarios (variables de entorno / `.env`)

- `ESIOS_TOKEN` — obligatorio, precios PVPC (indicador 1001 = precio final
  con peajes/cargos/margen ya incluidos, no es solo coste de mercado).
- `AEMET_TOKEN` — temperatura horaria.
- `ANTHROPIC_TOKEN` — búsqueda de consumo de aparatos con IA (Claude Haiku).

## Fórmula de facturación 2.0TD (verificada contra factura real)

Se dedujo y se verificó al céntimo contra una factura real de Energía XXI
(2.0TD con bono social). Constantes vigentes en 2026 (cambian cada año, las
fija la CNMC — hay que revisarlas si algo deja de cuadrar):

```
POT_ANUAL_P1LLANO = 27.704413   €/kW·año  (peajes+cargos potencia punta-llano)
POT_ANUAL_VALLE    = 0.725423   €/kW·año  (peajes+cargos potencia valle)
POT_ANUAL_MARGEN   = 3.113      €/kW·año  (margen de comercialización fijo)
ALQUILER_CONTADOR  = 0.026630   €/día
FINANC_BONO_SOCIAL = 0.019121   €/día     (cargo fijo, aparece incluso siendo beneficiario)
IMP_ELEC           = 5.1126963  %
IVA                = 21         %
```

Orden de cálculo (el orden importa, especialmente dónde se aplica el bono):

```
potencia = kW_contratada × (POT_ANUAL_P1LLANO + POT_ANUAL_VALLE + POT_ANUAL_MARGEN) × (días/365)
energía  = precio PVPC horario (ESIOS) × kWh consumidos  ← YA incluye peajes de energía, no sumar aparte
varios   = días × FINANC_BONO_SOCIAL

base           = potencia + energía + varios
descuento_bono = base × %bono          ← el bono se aplica sobre TODO (potencia+energía+varios), no solo sobre energía
base_imp_elec  = base − descuento_bono
imp_elec       = base_imp_elec × IMP_ELEC
alquiler       = días × ALQUILER_CONTADOR
subtotal       = base_imp_elec + imp_elec + alquiler
iva            = subtotal × IVA
TOTAL          = subtotal + iva
```

Implementado en `renderUploadResult()` en `templates/index.html` (sección
"Calcular desde fichero"). La calculadora principal (modo horas/franjas para
un aparato suelto) usa una versión más simple y **no** incluye este desglose
completo a propósito: es una herramienta de coste marginal ("¿cuánto me cuesta
encender el aire 2h?"), no una estimación de factura completa, así que ahí
sigue excluyendo deliberadamente el término de potencia.

La potencia contratada está hardcodeada en `UPLOAD_POTENCIA_KW = 5.75` (kW,
igual en P1 y P3). Si el usuario cambia de potencia contratada, hay que
actualizar esa constante.

### Modo tarifa "PVPC" (sin 2.0TD) — sí lleva IVA

Todos los cálculos tienen un selector de tarifa PVPC / PVPC 2.0TD. El modo
2.0TD aplica el desglose completo de arriba. El modo "PVPC" a secas sigue
siendo una herramienta de coste marginal (no incluye potencia, impuesto
eléctrico, alquiler de contador ni financiación bono social), **pero sí
aplica el IVA (21%)** sobre el término de energía con bono ya descontado —
antes no lo llevaba y mostraba un precio que no correspondía a lo que
realmente se paga. Patrón repetido en cada sitio que calcula un coste:
`is2otd ? (fórmula completa 2.0TD) : brutoConBono*(1+0.21)`. Si se añade un
nuevo sitio que muestre un coste en modo PVPC, seguir este mismo patrón.

## Subida de ficheros de consumo (`/api/consumption/upload`)

Parsea CSV/XLS/XLSX exportados por la distribuidora (formato tipo e-distribución).
Gotchas ya resueltos, por si se rompe con otro formato de fichero:

- **La cabecera real no está en la fila 0** — hay filas de metadatos antes
  (CUPS, fechas del periodo...). `parse_consumption_rows()` en `app.py` busca
  la primera fila que tenga columna de fecha + columna de hora + columna de
  consumo reconocible. Cuidado: una detección demasiado laxa (solo
  "contiene 'fecha' y 'hora' como substring") puede confundir una fila como
  "Fecha y hora de extracción" con la cabecera real — por eso se exige match
  de columna completa (`fecha`, `fecha_algo`) más una columna de consumo.
- **Unidades Wh vs kWh** — la columna de consumo puede venir en Wh (mira el
  header, p.ej. "Consumo (Wh)"). Se detecta por el nombre normalizado de la
  columna y se convierte a kWh (`value_unit_factor`).
- La columna "Hora" tiene **dos formatos vistos hasta ahora** en exports de la
  misma distribuidora, y hay que soportar ambos (`parse_hour_label()`):
  - Rango `"00:00-01:00"` → se coge el inicio del rango, sin desplazamiento.
  - Etiqueta numérica `1..24` ("hora que termina en") → `hour_of_day = label-1`.
    **La etiqueta 24 viene con la fecha del día SIGUIENTE** (es la costumbre
    de este exportador: la hora 23:00-24:00 de un día se guarda con la fecha
    de mañana). Si no se corrige, el periodo detectado sale un día más largo
    de lo real y se infla la potencia/alquiler/financiación bono social
    prorrateados — nos pasó: factura real 29 días pero el fichero parecía
    cubrir 30, con un descuadre de 0,25€ en el total. La corrección resta un
    día a la fecha cuando la etiqueta es 24.
- **Si el fichero trae columna de coste ya calculado** (p.ej. "Coste por hora
  (€)") con valores reales (no todo 0.0), se usa directamente como coste de
  la energía en vez de recalcular con ESIOS — es más preciso (coincide al
  céntimo con "Facturación por energía consumida" de la factura real) y no
  requiere `ESIOS_TOKEN`. Solo se cae a ESIOS si esa columna no existe o está
  toda a cero (algunos exports la traen vacía). Ver `file_has_cost` en
  `upload_consumption()`.
- Puede haber una fila de totales al final (`"Total (Wh): , 517319.0"`) — se
  descarta sola porque no tiene fecha parseable.

## Otras notas

- Bono social 2026: 42,5% (vulnerable) / 57,5% (severo), prorrogado por RDL
  16/2025. Para 2027 bajaría a 35%/50% salvo prórroga — revisar si cambia.
- El selector de skin (oscuro/claro/grafana/terminal/nord) es solo CSS
  (variables `:root` + clases `body.skin-*`), no hay lógica de negocio ahí.
- No hay tests automatizados ni CI configurado — los cambios se verifican
  manualmente (curl a los endpoints, o simulando el parseo con un script
  Python suelto) antes de desplegar.
