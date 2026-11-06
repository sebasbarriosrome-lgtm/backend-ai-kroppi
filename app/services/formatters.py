from datetime import date, datetime

from app.schemas import fecha_iso


def fechas(d: dict, *campos: str) -> dict:
    """Pasa datetimes/fechas a texto ISO para el JSON."""
    for c in campos:
        v = d.get(c)
        if isinstance(v, datetime):
            d[c] = fecha_iso(v)
        elif isinstance(v, date):
            d[c] = v.isoformat()
    return d


def cultivo_json(c: dict) -> dict:
    return fechas(c, "planted_at", "expected_harvest_at")


def lote_json(p: dict) -> dict:
    return fechas(p, "last_sampled_at")


def muestreo_json(m: dict) -> dict:
    return fechas(m, "sampled_at")
