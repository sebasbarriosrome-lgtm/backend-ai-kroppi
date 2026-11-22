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
WOMPI_PUBLIC_KEY=<clave-publica-de-Wompi>
WOMPI_INTEGRITY_SECRET=<secreto-de-integridad-de-Wompi>
WOMPI_EVENTS_SECRET=<secreto-de-eventos-de-Wompi>
WOMPI_PRIVATE_KEY=<llave-privada-de-Wompi>
WOMPI_API_URL=https://sandbox.wompi.co/v1
WOMPI_CHECKOUT_URL=https://checkout.wompi.co/p/
```

La clave `SUPABASE_SERVICE_ROLE_KEY` y las credenciales/secretos de Wompi solo deben
existir en el servidor. La API valida el JWT del usuario; para cultivos, verifica la
propiedad consultando `farms.owner_id` y relaciona cada cultivo por `crops.farm_id`.

Instala dependencias y ejecuta:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Suscripciones y cuotas

Aplica `migrations/006_subscription_limits.sql` y
`migrations/007_serialize_subscription_changes.sql` al esquema de Supabase
después de las migraciones 003–005 y antes de desplegar esta versión de la API. El plan
efectivo es Premium mientras `profiles.plan_type = 'premium'` y
`profiles.premium_until` esté en el futuro. El vencimiento devuelve la cuenta a
Free y conserva todos sus registros. La activación sigue a cargo del flujo
existente de Wompi. Precio informativo de Premium: $19.900 COP por 30 días.

`GET /subscription` devuelve el plan efectivo, su vencimiento activo, los
objetos `limits`, `usage` y `remaining`, el período de diagnósticos y
`premium_features_available`. Un límite o saldo `null` significa ilimitado.
Los límites Free son 1 finca, 2 cultivos y 5 lotes en toda la cuenta. Se cuentan
los cultivos archivados y sus lotes. Los triggers de PostgreSQL validan las
altas de FastAPI y las escrituras directas a Supabase. Las relaciones de
propiedad y de recurso padre quedan fijas tras crear el registro.
El límite de recursos devuelve HTTP 409.

Cuando la cuenta vuelve a Free, puede seguir consultando y editando sus
recursos aunque supere el límite. Cada categoría vuelve a admitir altas
cuando una eliminación permitida deja su contador por debajo del máximo.
Archivar un cultivo conserva su historial y mantiene ocupado su cupo. Una
reactivación de Premium amplía los límites y vuelve a habilitar el historial
completo con los datos existentes. Los cambios explícitos del plan y las
escrituras que consumen cuota se serializan por cuenta.

- Free conserva los muestreos, el estado de finca y lotes, el registro y la
  gestión puntual de cosechas y cuidados, el historial de muestreos en
  `timeline` y los diagnósticos del mes actual.
- Premium habilita el historial completo de diagnósticos, los listados de
  cosechas y cuidados, los eventos ampliados en `timeline`, las estadísticas,
  las estimaciones de pérdidas y los datos y archivos de informes PDF.
  Si el plan no autoriza una operación, FastAPI devuelve HTTP 403.
- Las políticas de Supabase también limitan las lecturas directas de
  diagnósticos, cosechas, cuidados, pérdidas e informes. Las URLs firmadas
  emitidas antes del vencimiento conservan su validez hasta su propia expiración.

La cuota de diagnósticos es de 3 intentos en Free y 30 en Premium por mes
calendario, desde las 00:00 del primer día en `America/Bogota` hasta el inicio
del mes siguiente. El mismo contador aplica cuando cambia el plan. Se registra
un intento después de validar la imagen, la propiedad del muestreo y el
modelo, inmediatamente antes de inferir. Los errores previos no consumen cuota.
Una vez autorizado, el intento se contabiliza aunque la inferencia o el
guardado falle. Eliminar el diagnóstico no devuelve el cupo. La migración
incorpora los diagnósticos que aún existen del mes en curso.

El agotamiento devuelve HTTP 429. Se puede enviar un UUID en el encabezado
`Idempotency-Key` de `POST /diagnoses`. Si ya se admitió la misma clave para
la cuenta, el servidor devuelve HTTP 409 sin volver a inferir ni descontar otro
cupo. Sin encabezado, cada solicitud válida se trata como un intento nuevo.

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

Todos los endpoints excepto `/health` y `/payments/webhook` requieren
`Authorization: Bearer <access_token>` de Supabase Auth. La documentación interactiva
está en `/docs`.

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
- `POST /payments/create` crea un pago pendiente de Premium y devuelve la URL del
  checkout de Wompi. Requiere un JWT de Supabase; el precio y la moneda los fija el
  servidor.
- `POST /payments/webhook` recibe eventos públicos de Wompi, valida el checksum y
  consulta la transacción con su API antes de confirmar el pago. No requiere JWT.
  La activación de Premium y el cambio del pago ocurren atómicamente mediante la
  función `public.confirm_wompi_payment`.

Antes de habilitar el webhook, ejecuta `migrations/005_confirm_wompi_payment.sql`
en el SQL Editor de Supabase. Configura en Wompi Sandbox la URL pública
`https://<dominio-api>/payments/webhook` como URL de eventos y habilita el evento
`transaction.updated`. La URL debe ser accesible por HTTPS.

Las fotos se guardan en el bucket privado y las respuestas contienen URLs firmadas
temporales. Gemini recibe únicamente los datos de la enfermedad, no la imagen.

Para probar el flujo completo en Sandbox: crea el checkout con un JWT válido,
completa el pago de prueba en Wompi y verifica que Wompi envíe
`transaction.updated` a la URL configurada. El webhook valida el evento, consulta la
transacción usando la llave privada y confirma `payments`/`profiles` en la base. No
se debe activar Premium desde la redirección del checkout.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest tests
```

Las pruebas de API y Wompi usan dobles. Las de suscripciones en PostgreSQL
ejecutan las migraciones y prueban concurrencia con conexiones independientes.
Para incluirlas, instala `psycopg[binary]`, configura
`KROPPI_TEST_POSTGRES_DSN` con un PostgreSQL local o desechable y vuelve a
ejecutar la suite. La conexión de pruebas debe poder crear bases y roles.
La suite crea y elimina su propia base temporal. Sin esa variable, pytest
omite las pruebas de integración.

Para probar `POST /payments/create`, inicia sesión en la app y copia el access token
de Supabase. En `/docs`, autoriza la petición con `Bearer <access_token>` y ejecuta el
endpoint sin cuerpo; la respuesta contiene la referencia, firma de integridad y URL
para abrir en el checkout web.
