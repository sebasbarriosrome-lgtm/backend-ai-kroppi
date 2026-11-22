import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from postgrest.exceptions import APIError

from app.core.security import Usuario, usuario_actual
from app.main import app
from app.services import (
    care_service, cosecha_service, diagnosis_service, stats_service,
    subscription_service, timeline_service,
)

USER = str(uuid4())
PLOT = str(uuid4())


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setitem(app.dependency_overrides, usuario_actual, lambda: Usuario(USER, None))
    # Exercise routing and authorization without loading the model or contacting Supabase.
    return TestClient(app)


def plan(premium=False):
    return {
        "plan_type": "premium" if premium else "free",
        "limits": {
            "farms": None if premium else 1,
            "crops": None if premium else 2,
            "plots": None if premium else 5,
            "diagnoses": 30 if premium else 3,
        },
        "diagnosis_period": {"starts_at": "2026-11-01T05:00:00+00:00"},
    }


def test_subscription_uses_authenticated_user_and_reports_remaining(client, monkeypatch):
    status = plan()
    status["usage"] = {"farms": 2, "crops": 2, "plots": 3, "diagnoses": 1}
    rpc = Mock(return_value=status)
    monkeypatch.setattr(subscription_service, "_rpc", rpc)
    response = client.get("/subscription?plan_type=premium&user_id=someone-else")
    assert response.status_code == 200
    assert response.json()["plan_type"] == "free"
    assert response.json()["remaining"] == {"farms": 0, "crops": 0, "plots": 2, "diagnoses": 2}
    rpc.assert_called_once_with("subscription_status", USER)


@pytest.mark.parametrize(
    ("method", "route", "params"),
    [
        ("GET", f"/plots/{PLOT}/stats", {}),
        ("GET", f"/plots/{PLOT}/report-data", {"from": "2026-11-01", "to": "2026-11-15"}),
        ("GET", f"/plots/{PLOT}/reports", {}),
        ("GET", f"/reports/{PLOT}", {}),
        ("DELETE", f"/reports/{PLOT}", {}),
        ("GET", f"/plots/{PLOT}/loss-estimations/defaults", {}),
        ("GET", f"/plots/{PLOT}/loss-estimations", {}),
        ("GET", f"/plots/{PLOT}/harvests", {}),
        ("GET", f"/plots/{PLOT}/care-activities", {}),
        ("GET", f"/plots/{PLOT}/timeline", {"types": "loss"}),
    ],
)
def test_free_cannot_use_premium_endpoints(client, monkeypatch, method, route, params):
    monkeypatch.setattr(subscription_service, "_rpc", Mock(return_value=plan()))
    response = client.request(method, route, params=params, headers={"X-Plan": "premium"})
    assert response.status_code == 403
    assert "Premium" in response.json()["detail"]


def test_plan_change_reflected_on_next_request(client, monkeypatch):
    rpc = Mock(side_effect=[plan(True), plan(), plan(True)])
    monkeypatch.setattr(subscription_service, "_rpc", rpc)
    stats = AsyncMock(return_value={"total": 1})
    monkeypatch.setattr(stats_service, "obtener", stats)
    assert client.get(f"/plots/{PLOT}/stats").json() == {"total": 1}
    assert client.get(f"/plots/{PLOT}/stats").status_code == 403
    assert client.get(f"/plots/{PLOT}/stats").json() == {"total": 1}
    assert stats.await_count == 2


def test_free_can_use_basic_history_and_register(client, monkeypatch):
    monkeypatch.setattr(subscription_service, "_rpc", Mock(return_value=plan()))
    timeline = AsyncMock(return_value={"items": [], "next_before": None})
    care = AsyncMock(return_value={"id": PLOT})
    harvest = AsyncMock(return_value={"id": PLOT, "affects_estimations": []})
    monkeypatch.setattr(timeline_service, "obtener", timeline)
    monkeypatch.setattr(care_service, "crear", care)
    monkeypatch.setattr(cosecha_service, "crear", harvest)
    assert client.get(f"/plots/{PLOT}/timeline").status_code == 200
    assert timeline.await_args.args[4] == ["sample"]
    assert client.post(f"/plots/{PLOT}/care-activities", json={
        "activity_type": "IRRIGATION", "applied_at": "2026-11-01",
    }).status_code == 201
    assert client.post(f"/plots/{PLOT}/harvests", json={
        "harvested_at": "2026-11-01", "quantity_kg": 10,
    }).status_code == 201
    assert harvest.await_args.kwargs == {"incluir_estimaciones": False}


def test_diagnosis_history_scoped_in_free(client, monkeypatch):
    monkeypatch.setattr(subscription_service, "_rpc", Mock(side_effect=[plan(), plan(True)]))
    monkeypatch.setattr(app.state, "http", object(), raising=False)
    history = Mock(return_value=[])
    monkeypatch.setattr(diagnosis_service.diagnosis_repository, "listar_diagnosticos", history)
    monkeypatch.setattr(diagnosis_service, "firmar_diagnosticos", AsyncMock(return_value=[]))

    assert client.get("/diagnoses").status_code == 200
    assert history.call_args.args[-1] == "2026-11-01T05:00:00+00:00"
    assert client.get("/diagnoses").status_code == 200
    assert history.call_args.args[-1] is None


@pytest.mark.parametrize(("response", "expected"), [
    (False, 409),
    (APIError({"code": "PT429", "message": "Cuota agotada"}), 429),
])
def test_quota_and_duplicate_stop_before_inference(client, monkeypatch, response, expected):
    rpc = Mock(side_effect=[response])
    predict = Mock()
    monkeypatch.setattr(subscription_service, "_rpc", rpc)
    monkeypatch.setattr(app.state, "http", object(), raising=False)
    monkeypatch.setattr(app.state, "classifiers", {
        "cafe": SimpleNamespace(predict=predict, class_to_code={}, class_names=[]),
    }, raising=False)
    monkeypatch.setattr(diagnosis_service.diagnosis_repository, "contexto_muestreo",
                        Mock(return_value={"crop_type": {"slug": "cafe"}}))
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="PNG")
    result = client.post(
        "/diagnoses", data={"plot_samples_id": PLOT},
        files={"file": ("leaf.png", image.getvalue(), "image/png")},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert result.status_code == expected
    rpc.assert_called_once()
    assert rpc.call_args.args == ("consume_diagnosis_quota", USER)
    predict.assert_not_called()


def test_failed_inference_is_charged_once_only_after_validation(client, monkeypatch):
    accepted = set()

    def rpc(_, user_id, *, p_diagnosis_id):
        key = (user_id, p_diagnosis_id)
        if key in accepted:
            return False
        accepted.add(key)
        return True

    predict = Mock(side_effect=RuntimeError("inference failed"))
    monkeypatch.setattr(subscription_service, "_rpc", rpc)
    monkeypatch.setattr(app.state, "http", object(), raising=False)
    monkeypatch.setattr(app.state, "classifiers", {
        "cafe": SimpleNamespace(predict=predict, class_to_code={}, class_names=[]),
    }, raising=False)
    monkeypatch.setattr(diagnosis_service.diagnosis_repository, "contexto_muestreo",
                        Mock(return_value={"crop_type": {"slug": "cafe"}}))
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="PNG")
    headers = {"Idempotency-Key": str(uuid4())}

    def submit(content):
        return client.post("/diagnoses", data={"plot_samples_id": PLOT}, headers=headers,
                           files={"file": ("leaf.png", content, "image/png")})

    assert submit(b"invalid").status_code == 400
    assert not accepted
    with pytest.raises(RuntimeError, match="inference failed"):
        submit(image.getvalue())
    assert submit(image.getvalue()).status_code == 409
    assert len(accepted) == 1
    predict.assert_called_once()
