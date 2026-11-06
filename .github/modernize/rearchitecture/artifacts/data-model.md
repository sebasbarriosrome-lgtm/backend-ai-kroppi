# Data Model

## Core entity graph
The backend expects a farm-driven crop domain where users own farms, farms contain crops, crops contain plots, plots contain sampling records, and each sampling record can have one or more diagnosis records.

- `users` / `profiles` — authenticated identity and profile metadata
- `farms` — owner-owned agricultural parcels or operations
- `crop_types` — catalog of supported crop classes (`coffee`, etc.) with thresholds and metadata
- `crops` — a user-owned cultivation record tied to a `farm_id` and a `crop_type_id`
- `plots` — a production unit inside a crop, with area and status
- `plot_samples` — sampling observations for a plot, with plant counts and incidence values
- `diagnostics` — image-based disease diagnosis records tied to a sample
- `harvests`, `loss_estimations` — adjacent domain models referenced by the readme and schema package but not fully surfaced in the active route layer

## Relationships
- `farms.owner_id -> users.id`
- `crops.farm_id -> farms.id`
- `crops.crop_type_id -> crop_types.id`
- `plots.crop_id -> crops.id`
- `plot_samples.plot_id -> plots.id`
- `diagnostics.plot_samples_id -> plot_samples.id`

## Business rules represented in code
- `crops`: archive instead of hard delete; `is_active` controls active vs archived listings.
- `plots`: status is derived from sample incidence against crop thresholds (`HEALTHY`, `ALERT`, `DANGER`).
- `plot_samples`: affected count cannot exceed evaluated count.
- `diagnostics`: uploaded image must be JPEG/PNG/WEBP under 10 MB and must match a valid crop type supported by the model.

## Key entity summary
- `TypeCultivo` (`crop_types`) holds `name`, `slug`, `alert_threshold_pct`, `danger_threshold_pct`, `avg_yield_kg_per_ha`, and catalog metadata.
- `Cultivo` (`crops`) tracks the crop record, planting time, expected harvest, and active/archive state.
- `Lote` (`plots`) tracks area, plant count, coordinates, and the latest health state.
- `Muestreo` (`plot_samples`) records observed incidence; it influences `plots.status` when a new sample is created.
- `Diagnostico` (`diagnostics`) stores AI prediction, disease code, confidence, recommendations, and image path metadata.

## Evidence in code
- `app/repository/helpers.py` defines the normalization functions for `crop_type`, `crop`, `plot`, `sample`, and `diagnostic` data.
- `app/repository/crop_repository.py`, `plot_repository.py`, `sample_repository.py`, and `diagnosis_repository.py` implement the Supabase access layer.
- `app/schemas/*.py` enumerates the request/response DTOs consumed by the API.
