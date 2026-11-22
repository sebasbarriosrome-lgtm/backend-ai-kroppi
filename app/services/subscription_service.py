from fastapi import Depends
from fastapi.concurrency import run_in_threadpool
from postgrest.exceptions import APIError

from app.core.exceptions import ReglaNegocio
from app.core.security import Usuario, usuario_actual
from app.db.session import supabase_client


def _rpc(name: str, user_id: str, **params):
    return supabase_client.rpc(name, {"p_user_id": user_id, **params}).execute().data


def _subscription_error(exc: APIError) -> None:
    if exc.code in {"PT409", "PT429"}:
        raise ReglaNegocio(int(exc.code[2:]), exc.message) from exc


def insertar_recurso(tabla: str, payload: dict) -> None:
    try:
        supabase_client.table(tabla).insert(payload).execute()
    except APIError as exc:
        _subscription_error(exc)
        raise


def _consumir_diagnostico(user_id: str, diagnosis_id: str) -> None:
    try:
        nuevo = _rpc("consume_diagnosis_quota", user_id, p_diagnosis_id=diagnosis_id)
    except APIError as exc:
        _subscription_error(exc)
        raise
    if nuevo is not True:
        raise ReglaNegocio(409, "Ya se procesó o está en curso un intento con esta clave.")


async def consumir_diagnostico(user_id: str, diagnosis_id: str) -> None:
    await run_in_threadpool(_consumir_diagnostico, user_id, diagnosis_id)


async def acceso(user_id: str) -> dict:
    return await run_in_threadpool(_rpc, "subscription_access", user_id)


async def estado(user_id: str) -> dict:
    estado = await run_in_threadpool(_rpc, "subscription_status", user_id)
    estado["remaining"] = {
        recurso: None if limite is None else max(0, limite - estado["usage"][recurso])
        for recurso, limite in estado["limits"].items()
    }
    estado["premium_features_available"] = es_premium(estado)
    return estado


def es_premium(acceso: dict) -> bool:
    return acceso["plan_type"] == "premium"


def inicio_historial_diagnosticos(acceso: dict) -> str | None:
    return None if es_premium(acceso) else acceso["diagnosis_period"]["starts_at"]


async def usuario_premium(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if not es_premium(await acceso(usuario.id)):
        raise ReglaNegocio(403, "Esta funcionalidad requiere un plan Premium activo.")
    return usuario
