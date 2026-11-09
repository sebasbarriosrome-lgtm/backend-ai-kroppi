import hashlib
import hmac
import re
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import httpx
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool

from app import config
from app.repository import payment_repository

PREMIUM_AMOUNT_IN_CENTS = 1_990_000
PAYMENT_CURRENCY = "COP"
WOMPI_STATUS = {
    "PENDING": "pending",
    "APPROVED": "approved",
    "DECLINED": "declined",
    "VOIDED": "voided",
    "ERROR": "error",
}


def generar_referencia() -> str:
    fecha = datetime.now(timezone.utc).strftime("%Y%m%d")
    return f"KROPPI-{fecha}-{uuid4().hex.upper()}"


def generar_firma_integridad(
    reference: str, amount_in_cents: int, currency: str, integrity_secret: str
) -> str:
    cadena = f"{reference}{amount_in_cents}{currency}{integrity_secret}"
    return hashlib.sha256(cadena.encode("utf-8")).hexdigest()


def validar_firma_evento(evento: dict, events_secret: str) -> bool:
    data = evento.get("data")
    signature = evento.get("signature")
    timestamp = evento.get("timestamp")
    if (
        not isinstance(data, dict)
        or not isinstance(signature, dict)
        or not isinstance(timestamp, int)
        or isinstance(timestamp, bool)
    ):
        return False

    properties = signature.get("properties")
    checksum = signature.get("checksum")
    if (
        not isinstance(properties, list)
        or not properties
        or not isinstance(checksum, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", checksum) is None
    ):
        return False

    valores = []
    for path in properties:
        if not isinstance(path, str) or not path or any(not part for part in path.split(".")):
            return False
        value: object = data
        for part in path.split("."):
            if not isinstance(value, dict) or part not in value:
                return False
            value = value[part]
        if value is None or isinstance(value, (dict, list)):
            return False
        if isinstance(value, bool):
            valores.append("true" if value else "false")
        else:
            valores.append(str(value))

    cadena = "".join(valores) + str(timestamp) + events_secret
    calculado = hashlib.sha256(cadena.encode("utf-8")).hexdigest()
    return hmac.compare_digest(calculado, checksum.lower())


def _transaction_fields(transaction: object) -> tuple[str, str, int, str, str]:
    if not isinstance(transaction, dict):
        raise HTTPException(400, "El evento de pago no tiene datos válidos.")

    transaction_id = transaction.get("id")
    reference = transaction.get("reference")
    amount = transaction.get("amount_in_cents")
    currency = transaction.get("currency")
    status = transaction.get("status")

    if (
        not isinstance(transaction_id, str)
        or not transaction_id
        or not isinstance(reference, str)
        or not reference
        or not isinstance(amount, int)
        or isinstance(amount, bool)
        or amount <= 0
        or not isinstance(currency, str)
        or not currency
        or not isinstance(status, str)
    ):
        raise HTTPException(400, "El evento de pago no tiene datos válidos.")
    return transaction_id, reference, amount, currency, status


async def procesar_evento(http: httpx.AsyncClient, evento: dict) -> None:
    if evento.get("event") != "transaction.updated":
        return

    if not config.WOMPI_EVENTS_SECRET:
        raise HTTPException(503, "El servicio de pagos no está configurado.")
    if not validar_firma_evento(evento, config.WOMPI_EVENTS_SECRET):
        raise HTTPException(400, "Firma de evento inválida.")
    if not config.WOMPI_API_URL or not config.WOMPI_PRIVATE_KEY:
        raise HTTPException(503, "El servicio de pagos no está configurado.")

    transaction = evento.get("data", {}).get("transaction")
    event_id, reference, amount, currency, event_status = _transaction_fields(
        transaction
    )
    if event_status not in WOMPI_STATUS:
        return

    try:
        response = await http.get(
            f"{config.WOMPI_API_URL}/transactions/{event_id}",
            headers={"Authorization": f"Bearer {config.WOMPI_PRIVATE_KEY}"},
        )
    except httpx.HTTPError as error:
        raise HTTPException(
            503, "No se pudo verificar la transacción con Wompi."
        ) from error

    if response.is_error:
        raise HTTPException(503, "No se pudo verificar la transacción con Wompi.")

    try:
        contenido = response.json()
    except ValueError as error:
        raise HTTPException(
            503, "No se pudo verificar la transacción con Wompi."
        ) from error

    datos_verificados = contenido.get("data") if isinstance(contenido, dict) else None
    try:
        (
            verified_id,
            verified_reference,
            verified_amount,
            verified_currency,
            verified_status,
        ) = _transaction_fields(datos_verificados)
    except HTTPException as error:
        raise HTTPException(
            503, "Wompi devolvió una respuesta de transacción inválida."
        ) from error
    if (
        verified_id != event_id
        or verified_reference != reference
        or verified_amount != amount
        or verified_currency != currency
    ):
        return

    estado = WOMPI_STATUS.get(verified_status)
    if estado is None:
        return

    try:
        await run_in_threadpool(
            payment_repository.confirmar_transaccion,
            verified_reference,
            verified_id,
            verified_amount,
            verified_currency,
            estado,
        )
    except payment_repository.PaymentConfirmationError as error:
        raise HTTPException(
            503, "No se pudo confirmar el pago. Wompi puede reintentar el evento."
        ) from error


def _crear_checkout_url(
    reference: str, amount_in_cents: int, currency: str, signature: str
) -> str:
    parametros = {
        "public-key": config.WOMPI_PUBLIC_KEY,
        "currency": currency,
        "amount-in-cents": amount_in_cents,
        "reference": reference,
        "signature:integrity": signature,
    }
    url = urlsplit(config.WOMPI_CHECKOUT_URL)
    query = dict(parse_qsl(url.query, keep_blank_values=True))
    query.update(parametros)
    return urlunsplit(
        (url.scheme, url.netloc, url.path, urlencode(query), url.fragment)
    )


async def crear_pago(user_id: str) -> dict:
    if not all(
        (
            config.WOMPI_PUBLIC_KEY,
            config.WOMPI_INTEGRITY_SECRET,
            config.WOMPI_CHECKOUT_URL,
        )
    ):
        raise HTTPException(503, "El servicio de pagos no está configurado.")

    reference = generar_referencia()
    amount_in_cents = PREMIUM_AMOUNT_IN_CENTS
    currency = PAYMENT_CURRENCY
    signature = generar_firma_integridad(
        reference, amount_in_cents, currency, config.WOMPI_INTEGRITY_SECRET
    )
    checkout_url = _crear_checkout_url(
        reference, amount_in_cents, currency, signature
    )
    datos_pago = {
        "user_id": user_id,
        "reference": reference,
        "provider": "wompi",
        "amount_in_cents": amount_in_cents,
        "currency": currency,
        "status": "pending",
        "provider_transaction_id": None,
        "paid_at": None,
    }

    try:
        await run_in_threadpool(payment_repository.crear_pago, datos_pago)
    except payment_repository.PaymentRepositoryError as error:
        raise HTTPException(
            502, "No se pudo registrar el pago. Intenta de nuevo."
        ) from error

    return {
        "reference": reference,
        "amount_in_cents": amount_in_cents,
        "currency": currency,
        "public_key": config.WOMPI_PUBLIC_KEY,
        "signature": signature,
        "checkout_url": checkout_url,
    }
