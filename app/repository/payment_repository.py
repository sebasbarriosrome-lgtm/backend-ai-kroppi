
import httpx
from postgrest.exceptions import APIError
from datetime import datetime, timedelta, timezone

from app.db.session import supabase_client


class PaymentRepositoryError(Exception):
    """Error al persistir un pago."""


class PaymentConfirmationError(Exception):
    """Error al confirmar un pago."""


def crear_pago(datos: dict) -> None:
    try:
        filas = (
            supabase_client.table("payments")
            .insert(datos)
            .select("id")
            .execute()
            .data
            or []
        )
    except (APIError, httpx.HTTPError) as error:
        raise PaymentRepositoryError from error

    if not filas:
        raise PaymentRepositoryError(
            "Supabase no confirmó la creación del pago."
        )


def confirmar_transaccion(
    reference: str,
    transaction_id: str,
    amount_in_cents: int,
    currency: str,
    status: str,
) -> dict:
    try:
        # 1. Buscar el pago por referencia
        resultado = (
            supabase_client.table("payments")
            .select("*")
            .eq("reference", reference)
            .eq("provider", "wompi")
            .maybe_single()
            .execute()
        )

        pago = resultado.data

        if not pago:
            raise PaymentConfirmationError(
                "No existe un pago con esa referencia."
            )

        # 2. Validar monto y moneda
        if (
            pago["amount_in_cents"] != amount_in_cents
            or pago["currency"] != currency
        ):
            raise PaymentConfirmationError(
                "Los datos del pago no coinciden."
            )

        # 3. Evitar asociar otra transacción al mismo pago
        if (
            pago.get("provider_transaction_id")
            and pago["provider_transaction_id"] != transaction_id
        ):
            raise PaymentConfirmationError(
                "El pago ya está asociado a otra transacción."
            )

        # 4. Evitar procesar nuevamente un pago aprobado
        if pago["status"] == "approved":
            return {"result": "already_processed"}

        # 5. Actualizar el pago
        ahora = datetime.now(timezone.utc)

        datos_actualizacion = {
            "provider_transaction_id": transaction_id,
            "status": status,
            "updated_at": ahora.isoformat(),
        }

        if status == "approved":
            datos_actualizacion["paid_at"] = ahora.isoformat()

        supabase_client.table("payments").update(
            datos_actualizacion
        ).eq("id", pago["id"]).execute()

        # 6. Si no fue aprobado, no activar Premium
        if status != "approved":
            return {
                "result": "payment_updated",
                "status": status,
            }

        # 7. Consultar perfil del usuario
        perfil_resultado = (
            supabase_client.table("profiles")
            .select("id, plan_type, premium_until")
            .eq("id", pago["user_id"])
            .maybe_single()
            .execute()
        )

        perfil = perfil_resultado.data

        if not perfil:
            raise PaymentConfirmationError(
                "No existe el perfil asociado al pago."
            )

        # 8. Calcular vencimiento
        premium_until = None

        if perfil.get("premium_until"):
            premium_until = datetime.fromisoformat(
                perfil["premium_until"].replace("Z", "+00:00")
            )

        if (
            perfil["plan_type"] == "premium"
            and premium_until
            and premium_until > ahora
        ):
            nueva_fecha = premium_until + timedelta(days=30)
        else:
            nueva_fecha = ahora + timedelta(days=30)

        # 9. Activar Premium
        supabase_client.table("profiles").update({
            "plan_type": "premium",
            "premium_until": nueva_fecha.isoformat(),
        }).eq("id", pago["user_id"]).execute()

        return {
            "result": "premium_activated",
            "premium_until": nueva_fecha.isoformat(),
        }

    except PaymentConfirmationError:
        raise
    except (APIError, httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        raise PaymentConfirmationError(
            "No se pudo completar la confirmación del pago."
        ) from error
