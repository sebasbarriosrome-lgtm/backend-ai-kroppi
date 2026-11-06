# Architecture Index

This index is not the full contract. Do not implement from this file alone; follow the artifact paths below.

## Global artifacts
- `unit_graph.yaml`
  - who reads: all implementation workers
  - use for: unit boundary, source anchors, exported signatures, shared refs, and inter-unit dependency map
  - how to consume: find the assigned unit and read its `source_anchors`, `exported_signature`, and `shared_refs`
- `migration_boundary.yaml`
  - who reads: all implementation workers
  - use for: implementation scope (`must_rewrite` vs `copy_as_is` vs `legacy_allowed_to_remain`)
  - how to consume: check whether the assigned unit is in the runtime-reachable boundary and whether the work is part of `must_rewrite`
- `wire_contracts.yaml`
  - who reads: workers touching external HTTP contracts
  - use for: route contract, request/response shapes, auth, and semantic drift
  - how to read: filter contracts where `unit` matches the assigned unit
- `shared_modules.yaml`
  - who reads: workers whose unit shares config/auth/helpers with another unit
  - use for: shared module inventory, god-class awareness, and migration strategy guidance
  - how to read: filter rows where `used_by_units` includes the assigned unit
- `cross_unit_state.yaml`
  - who reads: workers whose unit depends on app-scoped state or shared mutable objects
  - use for: implicit state flows and runtime confirmation requirements
  - how to read: filter rows whose `writer.unit` or `reader.unit` matches the assigned unit

## Unit: health
- external trigger: GET /health
- must read:
  - `units/health/behavior.yaml` — side effects, branches, error paths, and async semantics
  - `units/health/bindings.yaml` — router wiring and runtime config
  - `units/health/unit_decomposition.yaml` — split candidates only; do not treat as required target structure
- relevant global rows:
  - `wire_contracts.yaml` rows where `unit == health`
  - `shared_modules.yaml` rows where `used_by_units` includes `health`
- before DONE report: `artifacts_read`, `implemented_must_preserve`, `unresolved_or_deferred`, and verification evidence

## Unit: crops
- external trigger: GET/POST/PATCH/DELETE /crops and GET /crop-types
- must read:
  - `units/crops/behavior.yaml` — create/archive/update semantics and ownership validation
  - `units/crops/bindings.yaml` — auth and route binding obligations
  - `units/crops/unit_decomposition.yaml` — optional split guidance for crop admin logic vs persistence
- relevant global rows:
  - `wire_contracts.yaml` rows where `unit == crops`
  - `shared_modules.yaml` rows where `used_by_units` includes `crops`
  - `cross_unit_state.yaml` flows touching `crops`
- before DONE report: `artifacts_read`, `implemented_must_preserve`, `unresolved_or_deferred`, and verification evidence

## Unit: plots
- external trigger: GET/POST /crops/{crop_id}/plots and GET/PATCH /plots/{plot_id}
- must read:
  - `units/plots/behavior.yaml` — lot creation, validation, status semantics, and recent-diagnostics aggregation
  - `units/plots/bindings.yaml` — route/auth wiring and runtime config
  - `units/plots/unit_decomposition.yaml` — optional split guidance for lot data access vs display aggregation
- relevant global rows:
  - `wire_contracts.yaml` rows where `unit == plots`
  - `shared_modules.yaml` rows where `used_by_units` includes `plots`
  - `cross_unit_state.yaml` flows touching `plots`
- before DONE report: `artifacts_read`, `implemented_must_preserve`, `unresolved_or_deferred`, and verification evidence

## Unit: samples
- external trigger: POST/GET /plots/{plot_id}/samples
- must read:
  - `units/samples/behavior.yaml` — disease incidence calculation, validation, and status impact
  - `units/samples/bindings.yaml` — route/auth and config
  - `units/samples/unit_decomposition.yaml` — optional split guidance for sample collection vs status evaluation
- relevant global rows:
  - `wire_contracts.yaml` rows where `unit == samples`
  - `shared_modules.yaml` rows where `used_by_units` includes `samples`
  - `cross_unit_state.yaml` flows touching `samples`
- before DONE report: `artifacts_read`, `implemented_must_preserve`, `unresolved_or_deferred`, and verification evidence

## Unit: diagnoses
- external trigger: POST/GET /diagnoses; GET /diagnoses/{diagnostico_id}
- must read:
  - `units/diagnoses/behavior.yaml` — upload validation, inference output, recommendations, and storage cleanup
  - `units/diagnoses/bindings.yaml` — multipart route binding and configuration
  - `units/diagnoses/unit_decomposition.yaml` — optional split between upload/image processing and persistence
- relevant global rows:
  - `wire_contracts.yaml` rows where `unit == diagnoses`
  - `shared_modules.yaml` rows where `used_by_units` includes `diagnoses`
  - `cross_unit_state.yaml` flows touching `diagnoses`
- before DONE report: `artifacts_read`, `implemented_must_preserve`, `unresolved_or_deferred`, and verification evidence

## Completion evidence required for each implementation unit
- The implementation agent must read the unit-level behavior, bindings, and decomposition files.
- The agent must record which `must_preserve` items were implemented and which, if any, are deferred.
- The agent must leave explicit evidence of runtime verification or a documented reason a runtime check is not possible.
- The agent must not treat the `source_anchors` in `unit_graph.yaml` as automatic rewrite targets—scope comes from `migration_boundary.yaml::must_rewrite`.
