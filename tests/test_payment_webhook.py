import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import config
from app.repository import payment_repository
from app.routers.payments import router
from app.services import payment_service

AHORA = datetime(2026, 11, 8, 21, 0, tzinfo=timezone.utc)
REFERENCIA = "KROPPI-20261108-ABCDEF"
TRANSACCION_ID = "wompi-tx-123"


@pytest.fixture(autouse=True)
def wompi_config(monkeypatch):
    monkeypatch.setattr(config, "WOMPI_EVENTS_SECRET", "events-secret")
    monkeypatch.setattr(config, "WOMPI_PRIVATE_KEY", "private-test-key")
    monkeypatch.setattr(config, "WOMPI_API_URL", "https://sandbox.wompi.co/v1")


class AtomicPaymentDouble:
    """Simula el contrato de la RPC transaccional para las pruebas de servicio."""

    def __init__(self):
        self.payment = {
            "reference": REFERENCIA,
            "user_id": "valid-user",
            "provider": "wompi",
            "amount_in_cents": 1_990_000,
            "currency": "COP",
            "status": "pending",
            "provider_transaction_id": None,
            "paid_at": None,
        }
        self.profile = {"plan_type": "free", "premium_until": None}

    def confirmar_transaccion(
        self, reference, transaction_id, amount_in_cents, currency, status
    ):
        payment = self.payment
        if payment is None or payment["reference"] != reference:
            return {"result": "not_found"}
        if (
            payment["provider"] != "wompi"
            or payment["amount_in_cents"] != amount_in_cents
            or payment["currency"] != currency
            or payment["user_id"] is None
        ):
            return {"result": "mismatch"}
        if payment["provider_transaction_id"] not in (None, transaction_id):
            return {"result": "transaction_conflict"}
        if payment["status"] == "approved":
            return {"result": "already_processed"}

        payment["provider_transaction_id"] = transaction_id
        payment["status"] = status
        if status == "approved":
            payment["paid_at"] = AHORA
            current_expiry = self.profile["premium_until"]
            start = (
                current_expiry
                if self.profile["plan_type"] == "premium"
                and current_expiry is not None
                and current_expiry > AHORA
                else AHORA
            )
            self.profile["plan_type"] = "premium"
            self.profile["premium_until"] = start + timedelta(days=30)
        return {"result": "processed"}


def _transaction(
    *,
    status="APPROVED",
    reference=REFERENCIA,
    amount=1_990_000,
    currency="COP",
    transaction_id=TRANSACCION_ID,
):
    return {
        "id": transaction_id,
        "reference": reference,
        "amount_in_cents": amount,
        "currency": currency,
        "status": status,
    }


def _event(transaction, properties=None):
    data = {"transaction": transaction}
    properties = properties or [
        "transaction.status",
        "transaction.id",
        "transaction.amount_in_cents",
    ]
    timestamp = 1_799_000_000
    values = []
    for path in properties:
        value = data
        for segment in path.split("."):
            value = value[segment]
        values.append(str(value))
    checksum = hashlib.sha256(
        ("".join(values) + str(timestamp) + "events-secret").encode()
    ).hexdigest().upper()
    return {
        "event": "transaction.updated",
        "data": data,
        "signature": {"properties": properties, "checksum": checksum},
        "timestamp": timestamp,
    }


def _invoke(
    monkeypatch,
    event,
    *,
    wompi_transaction=None,
    http_status=200,
    store=None,
):
    calls = []

    def confirmar(*args):
        calls.append(args)
        if store is not None:
            return store.confirmar_transaccion(*args)
        return {"result": "processed"}

    monkeypatch.setattr(payment_repository, "confirmar_transaccion", confirmar)

    async def handler(request):
        assert request.url == (
            f"https://sandbox.wompi.co/v1/transactions/"
            f"{event['data']['transaction']['id']}"
        )
        assert request.headers["Authorization"] == "Bearer private-test-key"
        if http_status == 404:
            return httpx.Response(404)
        return httpx.Response(http_status, json={"data": wompi_transaction})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await payment_service.procesar_evento(http, event)

    asyncio.run(run())
    return calls


def test_webhook_aprobado_verifica_con_wompi_y_confirma_premium(
    monkeypatch,
):
    store = AtomicPaymentDouble()
    transaction = _transaction()
    event = _event(transaction, properties=["transaction.id", "transaction.reference"])

    calls = _invoke(
        monkeypatch, event, wompi_transaction=transaction, store=store
    )

    assert calls == [(REFERENCIA, TRANSACCION_ID, 1_990_000, "COP", "approved")]
    assert store.payment["status"] == "approved"
    assert store.payment["provider_transaction_id"] == TRANSACCION_ID
    assert store.payment["paid_at"] == AHORA
    assert store.profile["plan_type"] == "premium"
    assert store.profile["premium_until"] == AHORA + timedelta(days=30)


def test_firma_invalida_no_consulta_wompi_ni_actualiza(monkeypatch):
    store = AtomicPaymentDouble()
    event = _event(_transaction())
    event["signature"]["checksum"] = "0" * 64

    with pytest.raises(HTTPException) as error:
        _invoke(monkeypatch, event, wompi_transaction=_transaction(), store=store)

    assert error.value.status_code == 400
    assert store.payment["status"] == "pending"
    assert store.profile["plan_type"] == "free"


def test_transaccion_inexistente_en_wompi_no_confirma(monkeypatch):
    store = AtomicPaymentDouble()
    transaction = _transaction()
    event = _event(transaction)

    with pytest.raises(HTTPException) as error:
        _invoke(
            monkeypatch, event, wompi_transaction=None, http_status=404, store=store
        )

    assert error.value.status_code == 503
    assert store.payment["status"] == "pending"
    assert store.profile["plan_type"] == "free"


def test_estado_consultado_en_wompi_es_la_fuente_definitiva(monkeypatch):
    store = AtomicPaymentDouble()
    evento = _transaction(status="PENDING")
    verificada = _transaction(status="APPROVED")

    calls = _invoke(
        monkeypatch, _event(evento), wompi_transaction=verificada, store=store
    )

    assert calls == [(REFERENCIA, TRANSACCION_ID, 1_990_000, "COP", "approved")]
    assert store.profile["plan_type"] == "premium"


def test_evento_ajeno_a_transacciones_se_ignora(monkeypatch):
    store = AtomicPaymentDouble()
    event = {"event": "subscription.updated"}

    calls = _invoke(
        monkeypatch, event, wompi_transaction=None, store=store
    )

    assert calls == []
    assert store.payment["status"] == "pending"
    assert store.profile["plan_type"] == "free"


def test_referencia_inexistente_en_supabase_no_activa_premium(monkeypatch):
    store = AtomicPaymentDouble()
    store.payment = None
    transaction = _transaction()

    _invoke(
        monkeypatch,
        _event(transaction),
        wompi_transaction=transaction,
        store=store,
    )

    assert store.profile["plan_type"] == "free"


def test_monto_incorrecto_no_activa_premium(monkeypatch):
    store = AtomicPaymentDouble()
    transaction = _transaction(amount=1)

    _invoke(
        monkeypatch,
        _event(transaction),
        wompi_transaction=transaction,
        store=store,
    )

    assert store.payment["status"] == "pending"
    assert store.profile["plan_type"] == "free"


def test_moneda_incorrecta_no_activa_premium(monkeypatch):
    store = AtomicPaymentDouble()
    transaction = _transaction(currency="USD")

    _invoke(
        monkeypatch,
        _event(transaction),
        wompi_transaction=transaction,
        store=store,
    )

    assert store.payment["status"] == "pending"
    assert store.profile["plan_type"] == "free"


@pytest.mark.parametrize(
    ("wompi_status", "expected_status"),
    [("DECLINED", "declined"), ("PENDING", "pending")],
)
def test_transaccion_no_aprobada_no_activa_premium(
    monkeypatch, wompi_status, expected_status
):
    store = AtomicPaymentDouble()
    transaction = _transaction(status=wompi_status)

    _invoke(
        monkeypatch,
        _event(transaction),
        wompi_transaction=transaction,
        store=store,
    )

    assert store.payment["status"] == expected_status
    assert store.profile["plan_type"] == "free"
    assert store.profile["premium_until"] is None


def test_evento_duplicado_no_extiende_premium_dos_veces(monkeypatch):
    store = AtomicPaymentDouble()
    transaction = _transaction()
    event = _event(transaction)

    _invoke(monkeypatch, event, wompi_transaction=transaction, store=store)
    expiry_after_first = store.profile["premium_until"]
    _invoke(monkeypatch, event, wompi_transaction=transaction, store=store)

    assert expiry_after_first == AHORA + timedelta(days=30)
    assert store.profile["premium_until"] == expiry_after_first


def test_usuario_con_premium_vigente_conserva_dias_y_suma_30(monkeypatch):
    store = AtomicPaymentDouble()
    expiry = AHORA + timedelta(days=12)
    store.profile.update(plan_type="premium", premium_until=expiry)
    transaction = _transaction()

    _invoke(
        monkeypatch,
        _event(transaction),
        wompi_transaction=transaction,
        store=store,
    )

    assert store.profile["premium_until"] == expiry + timedelta(days=30)


def test_premium_vencido_se_reinicia_desde_fecha_actual(monkeypatch):
    store = AtomicPaymentDouble()
    store.profile.update(
        plan_type="premium", premium_until=AHORA - timedelta(days=1)
    )
    transaction = _transaction()

    _invoke(
        monkeypatch,
        _event(transaction),
        wompi_transaction=transaction,
        store=store,
    )

    assert store.profile["premium_until"] == AHORA + timedelta(days=30)


def test_fallo_de_supabase_responde_error_reintentable(monkeypatch):
    transaction = _transaction()
    event = _event(transaction)

    def falla(*_):
        raise payment_repository.PaymentConfirmationError

    monkeypatch.setattr(payment_repository, "confirmar_transaccion", falla)

    async def handler(_):
        return httpx.Response(200, json={"data": transaction})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            await payment_service.procesar_evento(http, event)

    with pytest.raises(HTTPException) as error:
        asyncio.run(run())

    assert error.value.status_code == 503


def test_reintento_despues_de_aprobado_no_vuelve_a_extender_premium(monkeypatch):
    store = AtomicPaymentDouble()
    transaction = _transaction()
    event = _event(transaction)

    _invoke(monkeypatch, event, wompi_transaction=transaction, store=store)
    expiry = store.profile["premium_until"]
    _invoke(monkeypatch, event, wompi_transaction=transaction, store=store)

    assert store.profile["premium_until"] == expiry


def test_evento_actualizado_de_wompi_es_publico_sin_jwt(monkeypatch):
    app = FastAPI()
    app.include_router(router)
    app.state.http = object()

    async def procesar_evento(http, evento):
        assert http is app.state.http
        assert evento["event"] == "transaction.updated"
        return None

    monkeypatch.setattr(payment_service, "procesar_evento", procesar_evento)

    with TestClient(app) as client:
        response = client.post(
            "/payments/webhook",
            json={"event": "transaction.updated", "data": {"transaction": {}}},
        )

    assert response.status_code == 200
    assert response.json() == {"received": True}
