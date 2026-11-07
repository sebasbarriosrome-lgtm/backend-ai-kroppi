# Kroppi API

API de FastAPI conectada a Supabase mediante su cliente Python y PostgREST. No requiere
`DATABASE_URL`, conexión directa a PostgreSQL ni `psycopg2`.

## Configuración

Define estas variables en `.env`:

```env
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=<clave-del-servidor>
SUPABASE_JWT_SECRET=<opcional-si-los-tokens-usan-HS256>
SUPABASE_BUCKET=diagnosticos
GEMINI_API_KEY=<opcional>
```

La clave `SUPABASE_SERVICE_ROLE_KEY` solo debe existir en el servidor. La API valida el
JWT del usuario; para cultivos, verifica la propiedad consultando `farms.owner_id` y
relaciona cada cultivo por `crops.farm_id`.

Instala dependencias y ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Esquema Supabase requerido

El esquema incluye `farms`, `crop_types`, `crops`, `plots`, `plot_samples`, `diagnostics`,
`harvests`, `loss_estimations`, `users` y `profiles`, con las relaciones y columnas
representadas en `app/models`. Los cultivos pertenecen a una finca mediante `farm_id`;
`owner_id` corresponde a `farms`. Cada diagnóstico se relaciona con `plot_samples` mediante
`diagnostics.plot_samples_id`.
La API no crea ni modifica las tablas existentes.

Las migraciones SQL anteriores (`001_seed_catalogo.sql` y `002_storage_y_politicas.sql`)
pertenecen al esquema inicial (`crops` como catálogo y `diseases`); no las ejecutes sobre
el esquema actual de modelos. El bucket privado `diagnosticos` debe existir y aceptar
imágenes JPEG.

## Endpoints

Todos los endpoints excepto `/health` requieren `Authorization: Bearer <access_token>` de
Supabase Auth. La documentación interactiva está en `/docs`.

- `GET /crop-types`, `GET/POST /crops`, `GET/PATCH/DELETE /crops/{crop_id}`
- `GET/POST /crops/{crop_id}/plots`, `GET/PATCH /plots/{plot_id}`
- `POST /plots/{plot_id}/samples` crea un muestreo con fechas y cantidades observadas.
- `POST /diagnoses` requiere `plot_samples_id` y una foto; `GET /diagnoses`,
  `GET /diagnoses/{diagnostico_id}` consultan el historial.
- `GET/POST /plots/{plot_id}/harvests`, `GET/PATCH/DELETE /harvests/{id}`: cosechas con
  moneda (`COP`/`USD`); los totales se agrupan por moneda y la escritura devuelve
  `affects_estimations`.
- `GET /plots/{plot_id}/loss-estimations/defaults`, `POST .../loss-estimations/preview`,
  `GET/POST /plots/{plot_id}/loss-estimations`, `GET/PATCH/DELETE /loss-estimations/{id}`:
  el agricultor indica los kg esperados, precio y periodo; el backend calcula lo cosechado
  y la pérdida (sin traslape de periodos por lote).
- `PATCH/DELETE /samples/{sample_id}` y `DELETE /diagnoses/{diagnostico_id}`.
- `GET /health`

Las fotos se guardan en el bucket privado y las respuestas contienen URLs firmadas
temporales. Gemini recibe únicamente los datos de la enfermedad, no la imagen.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

Las pruebas usan un doble en memoria de Supabase (`tests/conftest.py`); no tocan la base real.
