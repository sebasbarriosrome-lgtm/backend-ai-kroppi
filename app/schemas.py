"""Arma el JSON del contrato con la app. Sin dependencias externas, fácil de probar."""
from datetime import datetime, timezone


def fecha_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _enfermedad_json(d: dict | None):
    if d is None:
        return None
    return {
        "id": d["id"],
        "code": d["code"],
        "name": d["name"],
        "scientific_name": d["scientific_name"],
        "pathogen_type": d["pathogen_type"],
        "symptoms": d["symptoms"],
        "general_recommendations": d["general_recommendations"],
        "requires_agronomist": d["requires_agronomist"],
    }


def diagnostico_json(registro: dict, image_url: str) -> dict:
    enfermedad = registro.get("disease")
    nombre_comun = enfermedad["name"] if enfermedad else "Planta sana"
    nombre_cientifico = (enfermedad.get("scientific_name") if enfermedad else None) or "No especificado"

    return {
        "id": registro["id"],
        "image_url": image_url,
        "created_at": fecha_iso(registro["created_at"]),
        "ai_prediction": {
            "model_version": registro["model_version"],
            "confidence": float(registro["confidence"]),
            "disease_name": nombre_comun,
            "scientific_name": nombre_cientifico,
            "top": registro["top"],
            "recommendations": registro["recommendations"],
        },
        "crop": {
            "id": registro["crop"]["id"],
            "name": registro["crop"]["name"],
            "slug": registro["crop"]["slug"],
        },
        "disease": _enfermedad_json(registro["disease"]),
    }
