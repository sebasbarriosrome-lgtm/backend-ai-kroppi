import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.core.security import Usuario, usuario_actual
from app.repository import payment_repository
from app.routers.payments import router
from app.services import payment_service


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        yield app, client


@pytest.fixture(autouse=True)
def wompi_config(monkeypatch):
    monkeypatch.setattr(config, "WOMPI_PUBLIC_KEY", "pub_test_public")
    monkeypatch.setattr(config, "WOMPI_INTEGRITY_SECRET", "integrity-secret")
    monkeypatch.setattr(config, "WOMPI_CHECKOUT_URL", "https://checkout.wompi.co/p/")


def _autenticar(app, user_id="authenticated-user"):
    app.dependency_overrides[usuario_actual] = lambda: Usuario(
        id=user_id, email="user@example.com"
    )


def test_referencias_son_unicas():
    referencias = {payment_service.generar_referencia() for _ in range(100)}

    assert len(referencias) == 100
    assert all(ref.startswith("KROPPI-") for ref in referencias)


def test_firma_integridad_sha256():
    reference = "KROPPI-20261108-A8F92C"
    expected = hashlib.sha256(
        b"KROPPI-20261108-A8F92C1990000COPintegrity-secret"
    ).hexdigest()

    assert (
        payment_service.generar_firma_integridad(
            reference, 1_990_000, "COP", "integrity-secret"
        )
        == expected
    )


def test_creacion_fija_precio_moneda_y_guarda_pago_pendiente(
    api, monkeypatch
):
    app, client = api
    _autenticar(app)
    pagos_insertados = []
    monkeypatch.setattr(
        payment_repository, "crear_pago", pagos_insertados.append
    )

    response = client.post(
        "/payments/create",
        json={"user_id": "attacker", "amount_in_cents": 1, "currency": "USD"},
    )

    assert response.status_code == 201
    respuesta = response.json()
    assert respuesta["amount_in_cents"] == 1_990_000
    assert respuesta["currency"] == "COP"
    assert len(pagos_insertados) == 1
    assert pagos_insertados[0] == {
        "user_id": "authenticated-user",
        "reference": respuesta["reference"],
        "provider": "wompi",
        "amount_in_cents": 1_990_000,
        "currency": "COP",
        "status": "pending",
        "provider_transaction_id": None,
        "paid_at": None,
    }


def test_checkout_url_codifica_parametros_y_no_expone_secretos(
    api, monkeypatch
):
    app, client = api
    _autenticar(app)
    monkeypatch.setattr(payment_repository, "crear_pago", lambda _: None)
    monkeypatch.setenv("WOMPI_PRIVATE_KEY", "private-marker")

    response = client.post("/payments/create")

    assert response.status_code == 201
    respuesta = response.json()
    parametros = parse_qs(urlsplit(respuesta["checkout_url"]).query)
    assert parametros["public-key"] == ["pub_test_public"]
    assert parametros["currency"] == ["COP"]
    assert parametros["amount-in-cents"] == ["1990000"]
    assert parametros["reference"] == [respuesta["reference"]]
    assert parametros["signature:integrity"] == [respuesta["signature"]]
    assert "private_key" not in respuesta
    assert "private-marker" not in response.text
    assert "integrity-secret" not in response.text


def test_usuario_no_autenticado_no_puede_crear_pago(api, monkeypatch):
    _, client = api
    monkeypatch.setattr(
        payment_repository, "crear_pago", lambda _: pytest.fail("No debe insertar")
    )

    response = client.post("/payments/create")

    assert response.status_code == 401


def test_fallo_de_insercion_no_devuelve_checkout(api, monkeypatch):
    app, client = api
    _autenticar(app)

    def falla_insercion(_):
        raise payment_repository.PaymentRepositoryError

    monkeypatch.setattr(payment_repository, "crear_pago", falla_insercion)

    response = client.post("/payments/create")

    assert response.status_code == 502
    assert "checkout_url" not in response.json()
    assert "Supabase" not in response.text
