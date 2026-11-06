# Project Structure

## Summary
This repository is a Python backend API built with FastAPI and backed by a Supabase/PostgREST data layer. It exposes authenticated endpoints for crop management, plot management, sampling, and diagnosis workflows. It is not a frontend app or a monorepo; it is a single-service backend with a small model-serving component.

## Top-level module breakdown
- `app/` — application package
  - `main.py` — FastAPI app entrypoint, startup lifespan, middleware, router registration
  - `config/` — environment-backed runtime configuration and disease metadata
  - `core/` — cross-cutting auth and business-rule exceptions
  - `db/` — database client singleton
  - `routers/` — HTTP route definitions grouped by domain
  - `services/` — orchestration, validation, external calls, image processing, model inference
  - `repository/` — query layer over Supabase tables
  - `schemas/` — request/response DTOs and JSON helpers
  - `models/` — schema placeholders referenced by README and migration documentation
- `migrations/` — legacy SQL migration files that describe an earlier schema; not the active application data model
- `model_files/` — local TensorFlow Lite model and metadata consumed by `Classifier`
- `pruebas/` — local test imagery for validation and demos

## Layer architecture
- HTTP layer: `app/routers/*.py`
  - Defines endpoint routes, request validation, auth dependency injection, and the API surface.
- Service layer: `app/services/*.py`
  - Coordinates business rules, image processing, external storage, and model access.
- Repository layer: `app/repository/*.py`
  - Executes Supabase queries and performs model/plot/crop-specific data access.
- Persistence layer: Supabase/PostgREST tables (`farms`, `crop_types`, `crops`, `plots`, `plot_samples`, `diagnostics`)
  - Access is via the singleton client in `app/db/session.py`.
- Security layer: `app/core/security.py`
  - Verifies the user JWT and injects the authenticated user identity.
- Domain metadata/config layer: `app/config/settings.py`
  - Owns environment variables, model metadata, threshold values, and disease catalog.

## Entry points
- `app/main.py` is the runtime entrypoint for Uvicorn/FastAPI.
- Startup lifecycle (`lifespan`) initializes:
  - `app.state.classifier` via `Classifier()`
  - `app.state.http` via `httpx.AsyncClient(timeout=20)`
- Routers are mounted in `app.main`:
  - `/health`
  - `/crops`, `/crop-types`
  - `/plots`, `/crops/{crop_id}/plots`
  - `/plots/{plot_id}/samples`
  - `/diagnoses`

## File counts by package/layer
- `app/routers`: 6 files
- `app/services`: 9 files
- `app/repository`: 6 files
- `app/schemas`: 12 files
- `app/core`: 3 files
- `app/config`: 2 files
- `app/db`: 2 files

## Major functional domains
- Crop catalog and crop lifecycle
- Farm ownership and plot management
- Sampling and health-state evaluation
- Diagnostic image upload and disease inference
- Disease recommendation and signed image retrieval

## Project type classification
- Backend service
- FastAPI REST API
- Persistence via Supabase/PostgREST
- Model inference via local TFLite classifier
- Not a frontend or monorepo; one deployable API service with AI inference capability
