"""Acceso a datos. Funciones SÍNCRONAS (se llaman con run_in_threadpool).
El backend usa un rol que se salta RLS: TODA consulta filtra por propietario."""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from app import config
from app.database import (Crop, CropType, Diagnosis, Plot, PlotSample, SessionLocal)


class ReglaNegocio(Exception):
    """Error esperado (404, 400...). main.py lo convierte en respuesta HTTP."""
    def __init__(self, status: int, mensaje: str):
        self.status, self.mensaje = status, mensaje


def calcular_estado(incidencia: float, alerta: float, peligro: float) -> str:
    if incidencia >= peligro:
        return "DANGER"
    if incidencia >= alerta:
        return "ALERT"
    return "HEALTHY"


# ---------------------------------------------------------------- serializadores
def _tipo(t: CropType) -> dict:
    return {"id": t.id, "name": t.name, "slug": t.slug,
            "alert_threshold_pct": t.alert_threshold_pct,
            "danger_threshold_pct": t.danger_threshold_pct}


def _lote(p: Plot) -> dict:
    return {"id": p.id, "crop_id": p.crop_id, "name": p.name, "area_ha": p.area_ha,
            "plant_count": p.plant_count, "variety": p.variety,
            "latitude": p.latitude, "longitude": p.longitude, "status": p.status,
            "last_sampled_at": p.last_sampled_at}


def _cultivo(c: Crop) -> dict:
    estados = [p.status for p in c.plots]
    return {
        "id": c.id, "name": c.name, "planted_at": c.planted_at,
        "expected_harvest_at": c.expected_harvest_at, "is_active": c.is_active,
        "crop_type": _tipo(c.crop_type),
        "plots_summary": {
            "total": len(estados),
            "healthy": estados.count("HEALTHY"),
            "alert": estados.count("ALERT"),
            "danger": estados.count("DANGER"),
            "total_area_ha": round(sum(p.area_ha for p in c.plots), 2),
        },
    }


def _muestreo(m: PlotSample, estado: str | None = None) -> dict:
    return {"id": m.id, "plot_id": m.plot_id, "sampled_at": m.sampled_at,
            "plants_evaluated": m.plants_evaluated, "plants_affected": m.plants_affected,
            "incidence_pct": m.incidence_pct, "notes": m.notes, "status": estado}


def _registro(x: Diagnosis) -> dict:
    ia = x.ai_prediction or {}
    codigo = x.predicted_label
    return {
        "id": x.id, "image_path": x.image_url, "created_at": x.created_at,
        "model_version": ia.get("model_version", ""),
        "confidence": float(x.confidence if x.confidence is not None else ia.get("confidence", 0.0)),
        "top": ia.get("top", []),
        "recommendations": x.recommendations or ia.get("recommendations", []),
        "crop": _tipo(x.crop_type), "plot_id": x.plot_id,
        "disease": config.ENFERMEDADES.get(codigo) if codigo else None,
    }


# ---------------------------------------------------------------- helpers de propiedad
def _cargar_cultivo(db, user_id: str, crop_id: str) -> Crop:
    c = db.scalar(select(Crop)
                  .options(joinedload(Crop.crop_type), selectinload(Crop.plots))
                  .where(Crop.id == crop_id, Crop.owner_id == user_id))
    if c is None:
        raise ReglaNegocio(404, "Cultivo no encontrado.")
    return c


def _cargar_lote(db, user_id: str, plot_id: str) -> Plot:
    p = db.scalar(select(Plot).join(Crop, Plot.crop_id == Crop.id)
                  .options(joinedload(Plot.crop).joinedload(Crop.crop_type))
                  .where(Plot.id == plot_id, Crop.owner_id == user_id))
    if p is None:
        raise ReglaNegocio(404, "Lote no encontrado.")
    return p


# ---------------------------------------------------------------- catálogo
def listar_tipos() -> list[dict]:
    with SessionLocal() as db:
        filas = db.scalars(select(CropType).where(CropType.is_active.is_(True))
                           .order_by(CropType.name)).all()
        return [_tipo(t) for t in filas]


def tipo_por_slug(slug: str) -> dict | None:
    with SessionLocal() as db:
        t = db.scalar(select(CropType).where(CropType.slug == slug))
        return _tipo(t) if t else None


# ---------------------------------------------------------------- cultivos
def crear_cultivo(user_id: str, datos: dict) -> dict:
    with SessionLocal() as db:
        tipo = db.get(CropType, str(datos["crop_type_id"]))
        if tipo is None or not tipo.is_active:
            raise ReglaNegocio(400, "Tipo de cultivo no válido.")
        c = Crop(owner_id=user_id, crop_type_id=tipo.id, name=datos["name"].strip(),
                 planted_at=datos.get("planted_at"),
                 expected_harvest_at=datos.get("expected_harvest_at"))
        db.add(c)
        db.commit()
        return _cultivo(_cargar_cultivo(db, user_id, c.id))


def listar_cultivos(user_id: str, archivados: bool = False) -> list[dict]:
    with SessionLocal() as db:
        filas = db.scalars(
            select(Crop).options(joinedload(Crop.crop_type), selectinload(Crop.plots))
            .where(Crop.owner_id == user_id, Crop.is_active.is_(not archivados))
            .order_by(Crop.created_at.desc())).all()
        return [_cultivo(c) for c in filas]


def obtener_cultivo(user_id: str, crop_id: str) -> dict:
    with SessionLocal() as db:
        return _cultivo(_cargar_cultivo(db, user_id, crop_id))


def actualizar_cultivo(user_id: str, crop_id: str, cambios: dict) -> dict:
    with SessionLocal() as db:
        c = _cargar_cultivo(db, user_id, crop_id)
        for k, v in cambios.items():
            if k in ("name", "is_active") and v is None:
                continue
            setattr(c, k, v.strip() if k == "name" else v)
        if c.planted_at and c.expected_harvest_at and c.expected_harvest_at < c.planted_at:
            raise ReglaNegocio(400, "La cosecha estimada no puede ser anterior a la siembra.")
        db.commit()
        return _cultivo(_cargar_cultivo(db, user_id, crop_id))


# ---------------------------------------------------------------- lotes
def crear_lote(user_id: str, crop_id: str, datos: dict) -> dict:
    with SessionLocal() as db:
        c = _cargar_cultivo(db, user_id, crop_id)
        if not c.is_active:
            raise ReglaNegocio(400, "El cultivo está archivado.")
        p = Plot(crop_id=c.id, **{**datos, "name": datos["name"].strip()})
        db.add(p)
        db.commit()
        return _lote(p)


def listar_lotes(user_id: str, crop_id: str) -> list[dict]:
    with SessionLocal() as db:
        _cargar_cultivo(db, user_id, crop_id)   # verifica propiedad
        filas = db.scalars(select(Plot).where(Plot.crop_id == crop_id).order_by(Plot.name)).all()
        return [_lote(p) for p in filas]


def obtener_lote(user_id: str, plot_id: str) -> dict:
    with SessionLocal() as db:
        p = _cargar_lote(db, user_id, plot_id)
        ultimo = db.scalar(select(PlotSample).where(PlotSample.plot_id == plot_id)
                           .order_by(PlotSample.sampled_at.desc()).limit(1))
        return {**_lote(p),
                "crop": {"id": p.crop.id, "name": p.crop.name},
                "crop_type": _tipo(p.crop.crop_type),
                "last_sample": _muestreo(ultimo) if ultimo else None}


def actualizar_lote(user_id: str, plot_id: str, cambios: dict) -> dict:
    with SessionLocal() as db:
        p = _cargar_lote(db, user_id, plot_id)
        for k, v in cambios.items():
            if k in ("name", "area_ha") and v is None:
                continue
            setattr(p, k, v.strip() if k == "name" else v)
        if (p.latitude is None) != (p.longitude is None):
            raise ReglaNegocio(400, "Envía latitude y longitude juntas, o ninguna.")
        db.commit()
        return _lote(p)


def tipo_del_lote(user_id: str, plot_id: str) -> str:
    """crop_type_id del lote si es del usuario (404 si no). Lo usa POST /diagnoses."""
    with SessionLocal() as db:
        return _cargar_lote(db, user_id, plot_id).crop.crop_type_id


# ---------------------------------------------------------------- diagnósticos
def guardar_diagnostico(datos: dict) -> None:
    with SessionLocal() as db:
        db.add(Diagnosis(**datos))
        db.commit()


def _consulta_diag():
    return select(Diagnosis).options(joinedload(Diagnosis.crop_type))


def listar_diagnosticos(user_id: str, limite: int, desplazamiento: int,
                        plot_id: str | None = None) -> list[dict]:
    with SessionLocal() as db:
        q = _consulta_diag().where(Diagnosis.user_id == user_id)
        if plot_id:
            q = q.where(Diagnosis.plot_id == plot_id)
        filas = db.scalars(q.order_by(Diagnosis.created_at.desc())
                           .limit(limite).offset(desplazamiento)).all()
        return [_registro(f) for f in filas]


def obtener_diagnostico(user_id: str, diagnostico_id: str) -> dict:
    with SessionLocal() as db:
        f = db.scalar(_consulta_diag().where(Diagnosis.id == diagnostico_id,
                                             Diagnosis.user_id == user_id))
        if f is None:
            raise ReglaNegocio(404, "Diagnóstico no encontrado.")
        return _registro(f)


def diagnosticos_de_lote(user_id: str, plot_id: str, limite: int = 10) -> list[dict]:
    with SessionLocal() as db:
        _cargar_lote(db, user_id, plot_id)
    return listar_diagnosticos(user_id, limite, 0, plot_id)


# ---------------------------------------------------------------- muestreo
def crear_muestreo(user_id: str, plot_id: str, diag_ids: list[str], notas: str | None) -> dict:
    ids = list(dict.fromkeys(diag_ids))   # sin repetidos
    with SessionLocal() as db:
        lote = _cargar_lote(db, user_id, plot_id)
        diags = db.scalars(select(Diagnosis).where(
            Diagnosis.id.in_(ids), Diagnosis.user_id == user_id,
            Diagnosis.plot_id == plot_id)).all()
        if len(diags) != len(ids):
            raise ReglaNegocio(400, "Algunos diagnósticos no existen o no son de este lote.")

        # predicted_label=None significa "confianza bajo el umbral": no cuenta
        concluyentes = [d for d in diags if d.predicted_label]
        descartadas = len(diags) - len(concluyentes)
        if not concluyentes:
            raise ReglaNegocio(422, "Ninguna foto fue concluyente. Repite las fotos con mejor luz y enfoque.")

        evaluadas = len(concluyentes)
        afectadas = sum(1 for d in concluyentes if d.predicted_label != config.CODIGO_SANO)
        incidencia = round(afectadas / evaluadas * 100, 2)
        tipo = lote.crop.crop_type
        estado = calcular_estado(incidencia, tipo.alert_threshold_pct, tipo.danger_threshold_pct)

        ahora = datetime.now(timezone.utc)
        m = PlotSample(plot_id=plot_id, sampled_by=user_id, sampled_at=ahora, method="SAMPLING",
                       plants_evaluated=evaluadas, plants_affected=afectadas, notes=notas)
        db.add(m)
        lote.status = estado
        lote.last_sampled_at = ahora
        db.commit()
        return {**_muestreo(m, estado), "incidence_pct": incidencia, "discarded": descartadas}


def listar_muestreos(user_id: str, plot_id: str, limite: int = 50) -> list[dict]:
    with SessionLocal() as db:
        _cargar_lote(db, user_id, plot_id)
        filas = db.scalars(select(PlotSample).where(PlotSample.plot_id == plot_id)
                           .order_by(PlotSample.sampled_at.desc()).limit(limite)).all()
        return [_muestreo(m) for m in reversed(filas)]   # cronológico, listo para graficar