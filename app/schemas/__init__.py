from datetime import datetime, timezone

from .base import EstadoSalud, Latitud, Longitud, MetodoMuestreo, OutBase
from .cosecha import CosechaIn, CosechaOut, CosechaPatch
from .cultivo import CultivoIn, CultivoOut, CultivoPatch
from .diagnostico import DiagnosticoFeedback, DiagnosticoIn, DiagnosticoOut
from .estimacion_perdida import EstimacionPerdidaIn, EstimacionPerdidaOut
from .finca import FincaIn, FincaOut, FincaPatch
from .lote import LoteIn, LoteOut, LotePatch
from .muestreo import MuestreoIn, MuestreoOut, MuestreoPatch
from .perfil import PerfilOut, PerfilPatch
from .tipo_cultivo import TipoCultivoOut
from .usuario import UsuarioOut


def fecha_iso(valor: datetime | str) -> str:
    if isinstance(valor, str):
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enfermedad_json(enfermedad: dict | None) -> dict | None:
    if enfermedad is None:
        return None
    campos = (
        "code",
        "name",
        "scientific_name",
        "pathogen_type",
        "symptoms",
        "general_recommendations",
        "requires_agronomist",
    )
    return {campo: enfermedad.get(campo) for campo in campos}


def diagnostico_json(registro: dict, image_url: str) -> dict:
    enfermedad = registro.get("disease")
    return {
        "id": registro["id"],
        "plot_samples_id": registro["plot_samples_id"],
        "image_url": image_url,
        "created_at": fecha_iso(registro["created_at"]),
        "ai_prediction": {
            "model_version": registro["model_version"],
            "confidence": float(registro["confidence"]),
            "disease_name": enfermedad["name"] if enfermedad else "Planta sana",
            "scientific_name": (
                enfermedad.get("scientific_name") if enfermedad else None
            )
            or "No especificado",
            "top": registro["top"],
            "recommendations": registro["recommendations"],
        },
        "crop": {
            "id": registro["crop"]["id"],
            "name": registro["crop"]["name"],
            "slug": registro["crop"]["slug"],
        },
        "disease": _enfermedad_json(enfermedad),
    }


__all__ = [
    "EstadoSalud", "Latitud", "Longitud", "MetodoMuestreo", "OutBase",
    "diagnostico_json", "fecha_iso",
    "CosechaIn", "CosechaOut", "CosechaPatch",
    "CultivoIn", "CultivoOut", "CultivoPatch",
    "DiagnosticoFeedback", "DiagnosticoIn", "DiagnosticoOut",
    "EstimacionPerdidaIn", "EstimacionPerdidaOut",
    "FincaIn", "FincaOut", "FincaPatch",
    "LoteIn", "LoteOut", "LotePatch",
    "MuestreoIn", "MuestreoOut", "MuestreoPatch",
    "PerfilOut", "PerfilPatch",
    "TipoCultivoOut",
    "UsuarioOut",
]
