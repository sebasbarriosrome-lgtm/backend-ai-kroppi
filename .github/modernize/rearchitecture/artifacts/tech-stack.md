# Tech Stack

## Runtime and framework
- Python 3.x (project uses Python type hints and async/await)
- FastAPI for HTTP routing, validation, and startup lifecycle
- Uvicorn as the ASGI server entrypoint (implicit through standard local dev workflow)
- httpx for outbound async HTTP requests (for signed URLs and storage operations)

## Persistence and auth
- Supabase Python client (`supabase` package) for database and storage access
- Supabase Auth JWT validation using PyJWT and `PyJWKClient`
- Bearer-token authentication pattern enforced via FastAPI `Depends(usuario_actual)`

## ML / inference
- TensorFlow Lite model (`model_files/kroppi_cafe_v2.tflite`)
- Lightweight model metadata stored in `model_files/kroppi_config.json`
- `Pillow` for image preprocessing
- `numpy` for probability arrays and top-k ranking

## Data and utility libraries
- `python-dotenv` for environment loading
- `pydantic`/Pydantic v2 model validation implicitly used via FastAPI request bodies
- `numpy` and `Pillow` as the main image-processing stack

## Runtime configuration and operational concerns
- `app/config/settings.py` centralizes environment variables and metadata values.
- Model thresholds, disease mappings, and health rules are static configuration rather than DB-driven configuration.
- External configuration is loaded from `.env`; required values include `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

## Notable migration blockers or architectural constraints
- Runtime behavior is tightly coupled to Supabase table names and PostgREST query semantics.
- Business logic and persistence are separated through repository modules but still rely on backend-specific table contracts.
- Auth depends on Supabase-issued JWTs and JWT issuer validation; replacing the auth mechanism would require a broad contract change.
- The TFLite classifier is local and app-scoped through `app.state.classifier`; this is a startup-bound singleton pattern, not a shared-service model.
