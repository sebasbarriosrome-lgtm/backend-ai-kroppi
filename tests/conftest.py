"""Doble en memoria de Supabase para probar cosechas, pérdidas y estadísticas
sin red. Reemplaza las funciones de los repositorios; los servicios no cambian."""
import asyncio
import copy
import uuid
from datetime import date, datetime

import pytest

from app.core.exceptions import ReglaNegocio
from app.repository import cosecha_perdida_repository as repo
from app.repository import plot_modules_repository as modulos
from app.services import tiempo

USUARIO_A = "user-a"
USUARIO_B = "user-b"
LOTE_A = "plot-a"
LOTE_B = "plot-b"


def correr(coro):
    return asyncio.run(coro)


def _a_texto(datos: dict) -> dict:
    """Simula lo que devuelve Supabase: números como texto/num y fechas ISO."""
    salida = {}
    for clave, valor in datos.items():
        if hasattr(valor, "isoformat"):
            valor = valor.isoformat()
        elif valor.__class__.__name__ == "Decimal":
            valor = str(valor)
        salida[clave] = valor
    return salida


class BaseFalsa:
    def __init__(self):
        self.lotes = {
            LOTE_A: self._lote(LOTE_A, USUARIO_A),
            LOTE_B: self._lote(LOTE_B, USUARIO_B),
        }
        self.harvests: dict[str, dict] = {}
        self.losses: dict[str, dict] = {}

    @staticmethod
    def _lote(plot_id: str, owner: str) -> dict:
        return {
            "id": plot_id, "name": f"Lote {plot_id}", "area_ha": "2", "owner": owner,
            "crop": {
                "id": f"crop-{plot_id}", "name": "Café", "planted_at": "2024-01-15",
                "crop_type": {
                    "name": "Café", "avg_yield_kg_per_ha": "600",
                    "alert_threshold_pct": 10, "danger_threshold_pct": 20,
                },
                "farm": {"id": "farm", "name": "Finca", "owner_id": owner},
            },
        }

    # ---- lote ----
    def lote_propietario(self, user_id, plot_id):
        lote = self.lotes.get(plot_id)
        if lote is None or lote["owner"] != user_id:
            raise ReglaNegocio(404, "Lote no encontrado.")
        return copy.deepcopy(lote)

    # ---- cosechas ----
    def cosechas(self, plot_id, desde=None, hasta=None, limite=None, offset=0):
        rows = [
            h for h in self.harvests.values() if h["plot_id"] == plot_id
            and (desde is None or h["harvested_at"] >= desde.isoformat())
            and (hasta is None or h["harvested_at"] <= hasta.isoformat())
        ]
        rows.sort(key=lambda h: (h["harvested_at"], h["created_at"]), reverse=True)
        if limite is not None:
            rows = rows[offset:offset + limite]
        return copy.deepcopy(rows)

    def cosechas_asc(self, plot_id, desde, hasta):
        return list(reversed(self.cosechas(plot_id, desde, hasta)))

    def _uno(self, tabla, registro_id, mensaje):
        if registro_id not in tabla:
            raise ReglaNegocio(404, mensaje)
        return copy.deepcopy(tabla[registro_id])

    def cosecha_por_id(self, harvest_id):
        return self._uno(self.harvests, harvest_id, "Cosecha no encontrada.")

    def crear_cosecha(self, datos):
        row = {"id": str(uuid.uuid4()), "notes": None, "price_per_kg": None,
               "currency": "COP", **_a_texto(datos)}
        self.harvests[row["id"]] = row
        return copy.deepcopy(row)

    def actualizar_cosecha(self, harvest_id, datos):
        self.harvests[harvest_id].update(_a_texto(datos))
        return copy.deepcopy(self.harvests[harvest_id])

    def borrar_cosecha(self, harvest_id):
        self.harvests.pop(harvest_id, None)

    # ---- estimaciones ----
    def estimaciones(self, plot_id, limite=None, offset=0):
        rows = [e for e in self.losses.values() if e["plot_id"] == plot_id]
        rows.sort(key=lambda e: e["created_at"], reverse=True)
        if limite is not None:
            rows = rows[offset:offset + limite]
        return copy.deepcopy(rows)

    def estimacion_por_id(self, estimation_id):
        return self._uno(self.losses, estimation_id, "Estimación no encontrada.")

    def crear_estimacion(self, datos):
        row = {"id": str(uuid.uuid4()), **_a_texto(datos)}
        self.losses[row["id"]] = row
        return copy.deepcopy(row)

    def actualizar_estimacion(self, estimation_id, datos):
        self.losses[estimation_id].update(_a_texto(datos))
        return copy.deepcopy(self.losses[estimation_id])

    def borrar_estimacion(self, estimation_id):
        self.losses.pop(estimation_id, None)


@pytest.fixture
def bd(monkeypatch):
    base = BaseFalsa()
    monkeypatch.setattr(modulos, "lote_propietario", base.lote_propietario)
    monkeypatch.setattr(modulos, "cosechas", base.cosechas_asc)
    for nombre in ("muestreos", "cuidados", "diagnosticos"):
        monkeypatch.setattr(modulos, nombre, lambda *a, **k: [])
    for nombre in (
        "cosechas", "cosecha_por_id", "crear_cosecha", "actualizar_cosecha", "borrar_cosecha",
        "estimaciones", "estimacion_por_id", "crear_estimacion", "actualizar_estimacion",
        "borrar_estimacion",
    ):
        monkeypatch.setattr(repo, nombre, getattr(base, nombre))
    # "Hoy" fijo: 7 de noviembre de 2026 a las 10:00 en Bogotá.
    monkeypatch.setattr(tiempo, "ahora", lambda: datetime(2026, 11, 7, 10, 0, tzinfo=tiempo.BOGOTA))
    return base


@pytest.fixture
def d():
    return date.fromisoformat
