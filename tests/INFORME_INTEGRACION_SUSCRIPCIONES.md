# Integración de suscripciones de Kroppi

## Entorno

- Backend en `D:\Documentos\kroppi_backend`, rama `feat/enforce-subscription-plan-limits`. Frontend en `D:\Documentos\front_cropguard\cropguard`, rama `feat/subscription-plan-access-control`. Se probaron los árboles de trabajo, que incluían archivos de implementación sin commit en ambas ramas.
- Windows, Python 3.14.5, pytest 9.2.0, psycopg 3.3.9, PostgreSQL 18.7, Flutter 3.44.8 y Dart 3.12.2. Dependencias del backend fijadas en `requirements.txt`, entre ellas FastAPI 0.162.0, Uvicorn 0.54.0 y PyJWT 2.15.1.
- PostgreSQL escuchó solo en loopback. La fixture crea una base con nombre aleatorio, instala el esquema mínimo y las migraciones 003 a 007, comprueba su comportamiento y elimina la base al finalizar. El clúster se detuvo tras la ejecución.
- La prueba HTTP arranca Uvicorn en un puerto efímero, monta el router de suscripción del backend y ejecuta Flutter en otro proceso. Usa Dio, el modelo `SubscriptionAccess`, el `SubscriptionCubit`, el validador de JWT de FastAPI y el SQL real. Un adaptador reemplaza el transporte PostgREST para llamar a `subscription_status` con el rol `service_role`. La suite genera JWT HS256 efímeros y los pasa al cliente mediante variables de proceso. No se ejecutó el ciclo de autenticación de Supabase, el arranque del clasificador, Gemini, Storage ni Wompi real.

## Contrato y rutas

`GET /subscription` toma el usuario del JWT Bearer. FastAPI deriva `remaining` a partir de `limits` y `usage`, y expone `premium_features_available`. Flutter interpreta `plan_type`, `premium_until`, el inicio y la renovación de `diagnosis_period` y las cuotas `farms`, `crops`, `plots` y `diagnoses`. Las cuotas ilimitadas se transmiten como `null`. Si el consumo supera el máximo tras un downgrade, `remaining` es cero y `usage` conserva el total.

`KroppiApp` consulta la ruta mediante `FastApiClient`. `ApiAuthInterceptor` lee la sesión de Supabase. El Cubit refresca por cambio de cuenta, reanudación y vencimiento, y la navegación y los formularios solicitan actualizaciones. Las denegaciones 403, 409 y 429 de las operaciones FastAPI disparan una consulta adicional. Los formularios vuelven a comprobar el cupo antes de una creación y distinguen creación de edición.

La creación de fincas pasa por `FarmRemoteDataSource` y la tabla `farms` de Supabase. Cultivos y lotes tienen `POST /crops` y `POST /crops/{crop_id}/plots` en FastAPI. Los diagnósticos tienen `POST /diagnoses` y `GET /diagnoses`. Los módulos de lote exponen `/plots/{plot_id}/stats`, `/timeline`, `/report-data`, `/reports` y `/loss-estimations` bajo el prefijo del lote. El checkout usa `POST /payments/create` y el backend procesa `POST /payments/webhook`.

## Matriz de casos

| Caso | Capa y evidencia | Estado |
| --- | --- | --- |
| Estado Free y Premium con usuarios distintos | Flutter → TCP → FastAPI → PostgreSQL. HTTP 200, límites 1/2/5/3 y sin máximo de recursos en Premium con cuota 30. El Cubit refleja el consumo y los beneficios de cada cuenta. | APROBADO |
| Estado después de vencer Premium con 10 fincas, 8 cultivos, 12 lotes y 4 diagnósticos | Flutter → TCP → FastAPI → PostgreSQL. HTTP 200, plan Free, consumos conservados, cero cupo y diagnóstico deshabilitado. El vencimiento se prepara antes de conectar Flutter. | APROBADO |
| JWT ausente, inválido y expirado | HTTP 401 real. Un refresco con JWT expirado vacía el acceso del Cubit y presenta estado de error. El cambio local a cuenta nula limpia el estado. | APROBADO |
| Segunda finca, tercer cultivo y sexto lote, y cupo tras eliminar registros | Inserciones y consultas reales en PostgreSQL con triggers. Se comprueban aceptación hasta el límite, rechazo al superarlo y reapertura tras eliminación. | APROBADO |
| Cuota mensual Free 3 y Premium 30 | RPC SQL real, rechazo del cuarto y del diagnóstico 31, idempotencia, reinicio del periodo y recuento al migrar registros existentes. | APROBADO |
| Downgrade y reactivación con 10/8/12 | PostgreSQL real. Se verifican identificadores conservados, edición autorizada, creaciones rechazadas, historial almacenado y visibilidad por plan, consumo conservado y recuperación de beneficios. | APROBADO |
| Aislamiento de propiedad y del plan, concurrencia y downgrade durante escrituras | PostgreSQL real. Pruebas de políticas y escrituras simultáneas cerca de los máximos, incluido el consumo de cuota. | APROBADO |
| Estadísticas, informes, pérdidas, cosechas, cuidados e historial según plan | `TestClient` en proceso con usuario, RPC o servicios sustituidos según el caso. Las denegaciones Premium comprueban el HTTP 403 y su mensaje. | APROBADO |
| Mensajes de límite y diagnóstico, refresco, errores, sesión anterior y formularios | Suites automatizadas de Flutter con cargas y servicios simulados según el caso. | APROBADO |
| Fincas desde Flutter por Supabase, login/logout Supabase, emisor real y JWKS | Hace falta una instancia aislada de Supabase Auth/PostgREST con el esquema completo y cuentas de prueba. No se usó el proyecto configurado en la aplicación. | BLOQUEADO |
| Creaciones, ediciones y eliminaciones de extremo a extremo, incluyendo cultivos y lotes por FastAPI | La prueba TCP monta el router de suscripciones y la fixture SQL usa tablas mínimas. No valida las rutas de escritura con el esquema completo de Supabase. | BLOQUEADO |
| Inferencia y persistencia de diagnósticos por TCP; estadísticas Premium reales, informe PDF e historial en pantallas | Falta un entorno con el esquema completo, Storage aislado y dobles de inferencia conectados a los flujos HTTP. | BLOQUEADO |
| Pérdida de red real, reanudación, navegación a planes, cambio de cuota con pantalla abierta y reactivación desde la aplicación | La cobertura existente ejercita partes del estado con dobles o SQL y no se condujo una sesión completa de la app. | NO EJECUTADO |
| Pago real Wompi | Fuera de la ejecución por restricción expresa. La suite backend sí prueba el procesamiento con dobles. | NO EJECUTADO |

## Reproducción

Proveer un PostgreSQL local desechable cuyo usuario pueda crear bases y roles. Instalar `requirements-dev.txt` y `psycopg[binary]` en el entorno Python de pruebas y preparar las dependencias de Flutter. En el backend, establecer la URL y clave ficticias si la configuración local no las provee. Usar una configuración `.env` aislada si se crea un checkout específico para QA.

```powershell
$env:SUPABASE_URL = 'http://127.0.0.1:1'
$env:SUPABASE_SERVICE_ROLE_KEY = 'test-only'
$env:KROPPI_TEST_POSTGRES_DSN = '<DSN de PostgreSQL local desechable>'
$env:KROPPI_QA_FLUTTER_DIR = 'D:/Documentos/front_cropguard/cropguard'
.venv/Scripts/python.exe -m pytest -p no:cacheprovider -q -s
```

El cargador de configuración del backend da prioridad a un `.env` existente. La prueba TCP monta exclusivamente el router de suscripción y sustituye su acceso PostgREST, por lo que ese caso no usa la URL ni las claves remotas. El runner pasa la URL loopback y los JWT al proceso Flutter. El caso HTTP se omite en una corrida convencional de Flutter y requiere el runner para ejecutarse.

```powershell
flutter test --no-pub
flutter analyze --no-pub
```

## Resultados y cambios

- Backend e integración: 79 pruebas aprobadas, incluidas 17 de PostgreSQL y la ejecución Flutter por HTTP real. Frontend: 76 pruebas convencionales aprobadas y el caso de red aprobado desde el runner. Análisis estático sin hallazgos.
- La primera ejecución de la prueba nueva falló durante la recopilación por la ruta de importación de la fixture. Se corrigió la importación y se repitió la ejecución. No se reprodujeron fallos funcionales en los casos aprobados ni se modificaron reglas de negocio.
- Backend: nuevo `tests/test_subscription_flutter_http.py` y este informe. Frontend: nuevo `test/integration/subscription_http_test.dart`.
- Estado final parcial. Se verificó el contrato de lectura y la validación JWT por TCP, y las reglas de persistencia y concurrencia directamente en PostgreSQL. Sigue pendiente verificar el circuito completo mediante Supabase Auth/PostgREST y las pantallas con escrituras, informes e inferencia. No se hicieron cambios remotos, pagos, commits, merges ni push.
