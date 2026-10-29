"""Acceso a datos. Funciones SÍNCRONAS: desde los endpoints se llaman con run_in_threadpool
para no bloquear el servidor mientras se espera a la base de datos.

El backend se conecta con un rol de servidor que SE SALTA las políticas RLS, así que
cada consulta de diagnósticos filtra explícitamente por user_id."""
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app import config
from app.database import Crop, Diagnosis, Disease, SessionLocal


def _crop(c: Crop) -> dict:
    return {"id": c.id, "name": c.name, "slug": c.slug}


def _enfermedad(d: Disease) -> dict:
    return {
        "id": d.id,
        "code": d.code,
        "name": d.name,
        "scientific_name": d.scientific_name,
        "pathogen_type": d.pathogen_type,
        "symptoms": list(d.symptoms or []),
        "general_recommendations": list(d.general_recommendations or []),
        "requires_agronomist": bool(d.requires_agronomist),
        "is_healthy": d.code == config.CODIGO_SANO,
    }


def _registro(x: Diagnosis) -> dict:
    ia = x.ai_prediction or {}
    return {
        "id": x.id,
        "image_path": x.image_url,
        "created_at": x.created_at,
        "model_version": ia.get("model_version", ""),
        "confidence": ia.get("confidence", 0.0),
        "top": ia.get("top", []),
        "recommendations": ia.get("recommendations", []),
        "crop": _crop(x.crop),
        "disease": _enfermedad(x.disease) if x.disease else None,
    }


def cargar_catalogo(crop_slug: str):
    """Devuelve (cultivo, {code: enfermedad}) o (None, {})."""
    with SessionLocal() as db:
        cultivo = db.scalar(select(Crop).where(Crop.slug == crop_slug))
        if cultivo is None:
            return None, {}
        filas = db.scalars(select(Disease).where(Disease.crop_id == cultivo.id)).all()
        return _crop(cultivo), {d.code: _enfermedad(d) for d in filas}


def guardar_diagnostico(datos: dict) -> None:
    with SessionLocal() as db:
        db.add(Diagnosis(**datos))
        db.commit()


def listar_diagnosticos(user_id: str, limite: int, desplazamiento: int) -> list[dict]:
    with SessionLocal() as db:
        filas = db.scalars(
            select(Diagnosis)
            .options(joinedload(Diagnosis.crop), joinedload(Diagnosis.disease))
            .where(Diagnosis.user_id == user_id)
            .order_by(Diagnosis.created_at.desc())
            .limit(limite)
            .offset(desplazamiento)
        ).all()
        return [_registro(f) for f in filas]


def obtener_diagnostico(user_id: str, diagnostico_id: str) -> dict | None:
    with SessionLocal() as db:
        fila = db.scalar(
            select(Diagnosis)
            .options(joinedload(Diagnosis.crop), joinedload(Diagnosis.disease))
            .where(Diagnosis.id == diagnostico_id, Diagnosis.user_id == user_id)
        )
        return _registro(fila) if fila else None
