from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.core.exceptions import ReglaNegocio
from app.db.session import supabase_client
from app.repository.helpers import cargar_lote


def lote_propietario(user_id: str, plot_id: str) -> dict:
    return cargar_lote(user_id, plot_id)


def _lista(tabla: str, campo_fecha: str, plot_id: str, desde: date, hasta: date) -> list[dict]:
    inicio, fin = _limites(campo_fecha, desde, hasta)
    return (
        supabase_client.table(tabla)
        .select("*")
        .eq("plot_id", plot_id)
        .gte(campo_fecha, inicio)
        .lte(campo_fecha, fin)
        .order(campo_fecha)
        .execute()
        .data
        or []
    )


def _limites(campo_fecha: str, desde: date, hasta: date) -> tuple[str, str]:
    if campo_fecha in {"sampled_at", "created_at"}:
        zona = ZoneInfo("America/Bogota")
        return (
            datetime.combine(desde, time.min, tzinfo=zona).isoformat(),
            datetime.combine(hasta, time.max, tzinfo=zona).isoformat(),
        )
    return desde.isoformat(), hasta.isoformat()


def muestreos(plot_id: str, desde: date, hasta: date) -> list[dict]:
    return _lista("plot_samples", "sampled_at", plot_id, desde, hasta)


def cuidados(plot_id: str, desde: date, hasta: date) -> list[dict]:
    return _lista("care_activities", "applied_at", plot_id, desde, hasta)


def cosechas(plot_id: str, desde: date, hasta: date) -> list[dict]:
    return _lista("harvests", "harvested_at", plot_id, desde, hasta)


def perdidas(plot_id: str, desde: date, hasta: date) -> list[dict]:
    return _lista("loss_estimations", "created_at", plot_id, desde, hasta)


def informes(plot_id: str, limite: int = 100) -> list[dict]:
    return (
        supabase_client.table("plot_reports")
        .select("*")
        .eq("plot_id", plot_id)
        .order("created_at", desc=True)
        .limit(limite)
        .execute()
        .data
        or []
    )


def informes_periodo(plot_id: str, desde: date, hasta: date, limite: int = 200) -> list[dict]:
    inicio, fin = _limites("created_at", desde, hasta)
    return (
        supabase_client.table("plot_reports")
        .select("*")
        .eq("plot_id", plot_id)
        .gte("created_at", inicio)
        .lte("created_at", fin)
        .order("created_at", desc=True)
        .limit(limite)
        .execute()
        .data
        or []
    )


def perfil(user_id: str) -> dict:
    rows = (
        supabase_client.table("profiles")
        .select("id,full_name")
        .eq("id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return rows[0] if rows else {}


def muestras_por_ids(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    return (
        supabase_client.table("plot_samples")
        .select("id,plot_id,sampled_at,plants_evaluated,plants_affected,incidence_pct,method")
        .in_("id", ids)
        .execute()
        .data
        or []
    )


def ids_muestreos(plot_id: str) -> list[str]:
    rows = (
        supabase_client.table("plot_samples")
        .select("id")
        .eq("plot_id", plot_id)
        .execute()
        .data
        or []
    )
    return [row["id"] for row in rows]


def diagnosticos_historial(user_id: str, sample_ids: list[str]) -> list[dict]:
    if not sample_ids:
        return []
    return (
        supabase_client.table("diagnostics")
        .select("plot_samples_id,created_at,predicted_label,ai_prediction")
        .eq("user_id", user_id)
        .in_("plot_samples_id", sample_ids)
        .order("created_at")
        .limit(5000)
        .execute()
        .data
        or []
    )


def diagnosticos(
    user_id: str, sample_ids: list[str], desde: date, hasta: date
) -> list[dict]:
    if not sample_ids:
        return []
    inicio, fin = _limites("created_at", desde, hasta)
    return (
        supabase_client.table("diagnostics")
        .select("*")
        .eq("user_id", user_id)
        .in_("plot_samples_id", sample_ids)
        .gte("created_at", inicio)
        .lte("created_at", fin)
        .order("created_at")
        .execute()
        .data
        or []
    )


def listar_cuidados(
    plot_id: str, desde: date | None, hasta: date | None, tipo: str | None,
    limite: int, offset: int,
) -> list[dict]:
    query = supabase_client.table("care_activities").select("*").eq("plot_id", plot_id)
    if desde:
        query = query.gte("applied_at", desde.isoformat())
    if hasta:
        query = query.lte("applied_at", hasta.isoformat())
    if tipo:
        query = query.eq("activity_type", tipo)
    return (
        query.order("applied_at", desc=True)
        .range(offset, offset + limite - 1)
        .execute()
        .data
        or []
    )


def cuidado_por_id(activity_id: str) -> dict:
    rows = (
        supabase_client.table("care_activities")
        .select("*")
        .eq("id", activity_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ReglaNegocio(404, "Cuidado no encontrado.")
    return rows[0]


def crear_cuidado(datos: dict) -> dict:
    datos = {
        key: value.isoformat() if hasattr(value, "isoformat")
        else str(value) if isinstance(value, Decimal)
        else value
        for key, value in datos.items()
    }
    rows = (
        supabase_client.table("care_activities")
        .insert(datos)
        .select("*")
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError("Supabase no devolvió el cuidado creado.")
    return rows[0]


def actualizar_cuidado(activity_id: str, datos: dict) -> dict:
    datos = {
        key: value.isoformat() if hasattr(value, "isoformat")
        else str(value) if isinstance(value, Decimal)
        else value
        for key, value in datos.items()
    }
    rows = (
        supabase_client.table("care_activities")
        .update(datos)
        .eq("id", activity_id)
        .select("*")
        .execute()
        .data
        or []
    )
    if not rows:
        raise ReglaNegocio(404, "Cuidado no encontrado.")
    return rows[0]


def borrar_cuidado(activity_id: str) -> None:
    supabase_client.table("care_activities").delete().eq("id", activity_id).execute()


def actualizar_evidencia(activity_id: str, ruta: str | None) -> dict:
    rows = (
        supabase_client.table("care_activities")
        .update({"evidence_path": ruta})
        .eq("id", activity_id)
        .select("*")
        .execute()
        .data
        or []
    )
    if not rows:
        raise ReglaNegocio(404, "Cuidado no encontrado.")
    return rows[0]


def crear_informe(datos: dict) -> dict:
    rows = (
        supabase_client.table("plot_reports")
        .insert(datos)
        .select("*")
        .execute()
        .data
        or []
    )
    if not rows:
        raise RuntimeError("Supabase no devolvió el informe creado.")
    return rows[0]


def informe_por_id(report_id: str) -> dict:
    rows = (
        supabase_client.table("plot_reports")
        .select("*")
        .eq("id", report_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ReglaNegocio(404, "Informe no encontrado.")
    return rows[0]


def borrar_informe(report_id: str) -> None:
    supabase_client.table("plot_reports").delete().eq("id", report_id).execute()
