"""Exercise real authorization queries; only I/O and identity are simulated."""
import asyncio
import copy
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import jwt
import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.core.exceptions import ReglaNegocio
from app import config
from app.core import security
from app.repository import (
    cosecha_perdida_repository, diagnosis_repository, helpers,
    plot_modules_repository, plot_repository, sample_repository,
)
from app.routers import plot_modules, plots, samples
from app.services import storage


def uid(number):
    return str(UUID(int=number))


USERS = [uid(1), uid(2)]
FARMS = [uid(11), uid(12)]
CROPS = [uid(21), uid(22)]
PLOTS = [uid(31), uid(32)]
SAMPLES = [uid(41), uid(42)]
REPORTS = [uid(51), uid(52)]
TYPE = uid(61)
WHEN = "2026-11-07T10:00:00-05:00"
PERIOD = {"from": "2026-11-01", "to": "2026-11-10"}
TEST_ISSUER = "https://authorization-test.example.invalid/auth/v1"
TEST_SIGNING_KEY = "SYNTHETIC_TEST_ONLY_" * 4


class Database:
    def __init__(self):
        self.rows = {table: [] for table in (
            "farms", "crops", "plots", "plot_samples", "plot_reports",
            "crop_types", "profiles", "diagnostics", "care_activities",
            "harvests", "loss_estimations",
        )}
        self.effects, self.queries = [], []
        self.rows["crop_types"].append({
            "id": TYPE, "name": "Coffee", "slug": "coffee", "is_active": True,
            "alert_threshold_pct": 10, "danger_threshold_pct": 20,
            "avg_yield_kg_per_ha": 600,
        })
        for index in (0, 1):
            self.rows["farms"].append({"id": FARMS[index], "owner_id": USERS[index],
                                       "name": "Synthetic farm", "area_ha": 10})
            self.rows["crops"].append({"id": CROPS[index], "farm_id": FARMS[index],
                "crop_type_id": TYPE, "name": "Synthetic crop", "is_active": True,
                "planted_at": "2024-01-01"})
            self.rows["plots"].append({"id": PLOTS[index], "crop_id": CROPS[index],
                "name": "Synthetic private plot", "area_ha": 2, "status": "HEALTHY"})
            # Author metadata deliberately does not grant farm ownership.
            self.rows["plot_samples"].append({"id": SAMPLES[index], "plot_id": PLOTS[index],
                "sampled_by": USERS[1 - index], "sampled_at": WHEN, "method": "SAMPLING",
                "plants_evaluated": 100, "plants_affected": 10, "incidence_pct": 10,
                "notes": "Synthetic private sample"})
            self.rows["plot_reports"].append({"id": REPORTS[index], "plot_id": PLOTS[index],
                "created_by": USERS[1 - index], "created_at": WHEN,
                "period_from": PERIOD["from"], "period_to": PERIOD["to"],
                "file_path": f"{USERS[index]}/{PLOTS[index]}/{REPORTS[index]}.pdf",
                "file_size_bytes": 24, "summary": {}})
            self.rows["profiles"].append({"id": USERS[index], "full_name": "Synthetic owner"})

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.filters = []
        self.operation, self.payload = "select", None
        self.ordering = None
        self.start, self.stop = 0, None

    def select(self, *args, **kwargs):
        return self

    def eq(self, key, value):
        self.filters.append(lambda row: row.get(key) == value)
        return self

    def in_(self, key, values):
        self.filters.append(lambda row: row.get(key) in values)
        return self

    def gte(self, key, value):
        self.filters.append(lambda row: str(row.get(key, "")) >= str(value))
        return self

    def lte(self, key, value):
        self.filters.append(lambda row: str(row.get(key, "")) <= str(value))
        return self

    def order(self, key, desc=False):
        self.ordering = (key, desc)
        return self

    def limit(self, count):
        self.stop = self.start + count
        return self

    def range(self, start, end):
        self.start, self.stop = start, end + 1
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", copy.deepcopy(payload)
        return self

    def update(self, payload):
        self.operation, self.payload = "update", copy.deepcopy(payload)
        return self

    def delete(self):
        self.operation = "delete"
        return self

    def execute(self):
        self.db.queries.append((self.table, self.operation))
        rows = [row for row in self.db.rows[self.table]
                if all(predicate(row) for predicate in self.filters)]
        if self.operation == "insert":
            row = {"created_at": WHEN, **self.payload}
            self.db.rows[self.table].append(row)
            rows = [row]
        elif self.operation == "update":
            for row in rows:
                row.update(self.payload)
        elif self.operation == "delete":
            self.db.rows[self.table] = [row for row in self.db.rows[self.table] if row not in rows]
        if self.operation != "select":
            self.db.effects.append((self.table, self.operation))
        if self.ordering:
            key, reverse = self.ordering
            rows = sorted(rows, key=lambda row: str(row.get(key, "")), reverse=reverse)
        return SimpleNamespace(data=copy.deepcopy(rows[self.start:self.stop]))


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(config, "SUPABASE_JWT_SECRET", TEST_SIGNING_KEY)
    monkeypatch.setattr(security, "_ISSUER", TEST_ISSUER)
    db = Database()
    # Keep helpers.cargar_lote/cargar_cultivo and their owner_id filters real.
    for module in (helpers, plot_repository, sample_repository, plot_modules_repository,
                   diagnosis_repository, cosecha_perdida_repository):
        monkeypatch.setattr(module, "supabase_client", db)
    effects = {}
    for name in ("firmar_objeto", "firmar_objetos", "firmar_urls",
                 "subir_objeto", "eliminar_objeto", "eliminar_imagen"):
        result = "https://files.example.invalid/synthetic.pdf" if name == "firmar_objeto" else {}
        effects[name] = AsyncMock(return_value=result)
        monkeypatch.setattr(storage, name, effects[name])
    app = FastAPI()
    for router in (plots.router, samples.router, plot_modules.router):
        app.include_router(router)

    @app.exception_handler(ReglaNegocio)
    async def business_error(request: Request, error: ReglaNegocio):
        return JSONResponse({"detail": error.mensaje}, status_code=error.status)

    def unexpected_network(request):
        raise AssertionError("External requests disabled; storage must be simulated.")

    app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(unexpected_network))
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client, db=db, storage=effects)
    asyncio.run(app.state.http.aclose())


CASES = (
    "plot-create", "plot-list", "plot-get", "plot-update",
    "sample-create", "sample-list", "sample-update", "sample-delete",
    "stats", "timeline", "report-data",
    "report-create", "report-list", "report-get", "report-delete",
)


def request_case(case, index):
    crop, plot, sample, report = CROPS[index], PLOTS[index], SAMPLES[index], REPORTS[index]
    definition = {
        "plot-create": ("POST", f"/crops/{crop}/plots", 201,
                        {"json": {"name": "New synthetic plot", "area_ha": 1}}),
        "plot-list": ("GET", f"/crops/{crop}/plots", 200, {}),
        "plot-get": ("GET", f"/plots/{plot}", 200, {}),
        "plot-update": ("PATCH", f"/plots/{plot}", 200, {"json": {"name": "Updated plot"}}),
        "sample-create": ("POST", f"/plots/{plot}/samples", 201, {"json": {
            "sampled_at": WHEN, "plants_evaluated": 100, "plants_affected": 10}}),
        "sample-list": ("GET", f"/plots/{plot}/samples", 200, {}),
        "sample-update": ("PATCH", f"/samples/{sample}", 200, {"json": {"notes": "Updated note"}}),
        "sample-delete": ("DELETE", f"/samples/{sample}", 204, {}),
        "stats": ("GET", f"/plots/{plot}/stats", 200, {"params": PERIOD}),
        "timeline": ("GET", f"/plots/{plot}/timeline", 200, {"params": PERIOD}),
        "report-data": ("GET", f"/plots/{plot}/report-data", 200, {"params": PERIOD}),
        "report-create": ("POST", f"/plots/{plot}/reports", 201, {
            "data": {"period_from": PERIOD["from"], "period_to": PERIOD["to"]},
            "files": {"file": ("synthetic.pdf", b"%PDF-1.4 synthetic fixture", "application/pdf")}}),
        "report-list": ("GET", f"/plots/{plot}/reports", 200, {}),
        "report-get": ("GET", f"/reports/{report}", 200, {}),
        "report-delete": ("DELETE", f"/reports/{report}", 204, {}),
    }
    return definition[case]


def authenticate(api, user_id):
    # Real JWT verification with a test-only key; ownership is checked AFTER
    # authentication. No production credentials or dependency overrides.
    token = jwt.encode({"sub": user_id, "aud": "authenticated",
                        "iss": TEST_ISSUER, "exp": int(time.time()) + 3600},
                       TEST_SIGNING_KEY, algorithm="HS256")
    api.client.headers["Authorization"] = f"Bearer {token}"


@pytest.mark.parametrize("index", [0, 1], ids=["owner-A-resource", "owner-B-resource"])
@pytest.mark.parametrize("identity", ["owner", "other-user", "anonymous"])
@pytest.mark.parametrize("case", CASES)
def test_authorization_decision_across_real_routes(api, case, identity, index):
    if identity != "anonymous":
        authenticate(api, USERS[index if identity == "owner" else 1 - index])
    before = copy.deepcopy(api.db.rows)
    method, path, valid_status, arguments = request_case(case, index)
    response = api.client.request(method, path, **arguments)
    expected = valid_status if identity == "owner" else 401 if identity == "anonymous" else 404
    assert response.status_code == expected, (case, identity, response.status_code)
    if identity != "owner":
        assert api.db.rows == before
        assert api.db.effects == []
        assert all(effect.call_count == 0 for effect in api.storage.values())
        assert "file_path" not in response.text and "file_url" not in response.text
        if identity == "anonymous":
            assert api.db.queries == []
    else:
        assert PLOTS[1 - index] not in response.text
        if case == "report-get":
            assert api.storage["firmar_objeto"].await_count == 1
        if case == "report-delete":
            assert api.storage["eliminar_objeto"].await_count == 1


@pytest.mark.parametrize("index", [0, 1])
def test_client_cannot_reassign_plot_or_sample_parent_or_author(api, index):
    authenticate(api, USERS[index])
    response = api.client.patch(f"/plots/{PLOTS[index]}", json={
        "name": "Valid name", "crop_id": CROPS[1 - index], "owner_id": USERS[1 - index]})
    assert response.status_code == 200
    plot = next(row for row in api.db.rows["plots"] if row["id"] == PLOTS[index])
    assert plot["crop_id"] == CROPS[index]
    old_author = api.db.rows["plot_samples"][index]["sampled_by"]
    response = api.client.patch(f"/samples/{SAMPLES[index]}", json={
        "notes": "Valid note", "plot_id": PLOTS[1 - index], "sampled_by": USERS[index]})
    assert response.status_code == 200
    sample = next(row for row in api.db.rows["plot_samples"] if row["id"] == SAMPLES[index])
    assert sample["plot_id"] == PLOTS[index] and sample["sampled_by"] == old_author


@pytest.mark.parametrize("index", [0, 1])
def test_report_namespace_and_creator_come_from_authenticated_user(api, index):
    authenticate(api, USERS[index])
    method, path, _, arguments = request_case("report-create", index)
    arguments["data"].update(created_by=USERS[1 - index], file_path="other-user/private.pdf")
    response = api.client.request(method, path, **arguments)
    assert response.status_code == 201
    row = response.json()
    assert row["created_by"] == USERS[index] and row["plot_id"] == PLOTS[index]
    assert row["file_path"].startswith(f"{USERS[index]}/{PLOTS[index]}/")


def test_foreign_sample_deletion_never_deletes_diagnoses_or_storage(api):
    authenticate(api, USERS[1])
    api.db.rows["diagnostics"].append({"id": uid(71), "plot_samples_id": SAMPLES[0],
                                      "image_url": "synthetic-owner-A/photo.jpg"})
    before = copy.deepcopy(api.db.rows)
    response = api.client.delete(f"/samples/{SAMPLES[0]}")
    assert response.status_code == 404
    assert api.db.rows == before and not api.db.effects
    api.storage["eliminar_imagen"].assert_not_awaited()


@pytest.mark.parametrize("path", [f"/plots/{uid(99)}", f"/reports/{uid(99)}"])
def test_missing_resource_is_denied_without_storage_side_effects(api, path):
    authenticate(api, USERS[0])
    response = api.client.get(path)
    assert response.status_code == 404
    assert not api.db.effects
    assert all(effect.call_count == 0 for effect in api.storage.values())

