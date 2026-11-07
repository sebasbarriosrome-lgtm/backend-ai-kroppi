from datetime import datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.core.exceptions import ReglaNegocio
from app.schemas import PerdidaEstimadaCrear
from app.services import cosecha_service, perdida_service, stats_service, tiempo
from app.services.perdidas_calculo import calcular_perdida, formato_moneda
from tests.conftest import LOTE_A, USUARIO_A, USUARIO_B, correr


def _cosecha(d, fecha, kg, precio=None, moneda="COP", lote=LOTE_A):
    datos = {"harvested_at": d(fecha), "quantity_kg": Decimal(str(kg)),
             "price_per_kg": Decimal(str(precio)) if precio is not None else None,
             "currency": moneda, "notes": None}
    return correr(cosecha_service.crear(USUARIO_A, lote, datos))


def _estimacion(d, desde, hasta, esperado=1200, precio=9000, moneda="COP"):
    return {"expected_yield_kg": Decimal(str(esperado)), "price_per_kg": Decimal(str(precio)),
            "currency": moneda, "period_from": d(desde), "period_to": d(hasta), "notes": None}


# ---------------- Cálculo ----------------

def test_calculo_basico():
    r = calcular_perdida(Decimal(1200), Decimal(900), Decimal(9000), "COP")
    assert r["lost_kg"] == Decimal("300.00")
    assert r["loss_pct"] == Decimal("25.00")
    assert r["estimated_loss_amount"] == Decimal("2700000")
    assert r["explanation"] == (
        "Se esperaban 1.200 kg y se cosecharon 900 kg; faltaron 300 kg × $9.000/kg = $2.700.000"
    )


def test_cosechado_mayor_que_esperado():
    r = calcular_perdida(Decimal(1000), Decimal("1250.5"), Decimal(9000), "COP")
    assert r["lost_kg"] == 0 and r["estimated_loss_amount"] == 0
    assert r["surplus_kg"] == Decimal("250.50")
    assert r["explanation"].startswith("No hay pérdidas respecto a lo esperado")
    assert "250,5 kg" in r["explanation"]


def test_esperado_cero_rechazado(d):
    with pytest.raises(ValidationError):  # FastAPI lo responde como 422
        PerdidaEstimadaCrear(**_estimacion(d, "2026-01-01", "2026-02-01", esperado=0))
    with pytest.raises(ValueError):
        calcular_perdida(Decimal(0), Decimal(0), Decimal(1), "COP")


def test_decimal_sin_errores_de_punto_flotante():
    r = calcular_perdida(Decimal("0.3"), Decimal("0.1") + Decimal("0.2"), Decimal(1), "COP")
    assert r["lost_kg"] == 0 and r["surplus_kg"] == 0


def test_formato_usd():
    assert formato_moneda(Decimal("2700.5"), "USD") == "US$2,700.50"
    r = calcular_perdida(Decimal(10), Decimal(4), Decimal("1.25"), "USD")
    assert r["estimated_loss_amount"] == Decimal("7.50")


# ---------------- Cosechas ----------------

def test_cosecha_futura_rechazada(bd, d):
    with pytest.raises(ReglaNegocio) as error:
        _cosecha(d, "2026-11-08", 10)
    assert error.value.status == 400


def test_cosecha_antes_de_siembra_rechazada(bd, d):
    with pytest.raises(ReglaNegocio) as error:
        _cosecha(d, "2024-01-01", 10)
    assert "15/01/2024" in error.value.mensaje


def test_cosecha_2330_bogota_cae_en_el_dia_correcto(bd, d, monkeypatch):
    # 23:30 en Bogotá ya es el día siguiente en UTC: "hoy" debe seguir siendo el 7.
    monkeypatch.setattr(
        tiempo, "ahora", lambda: datetime(2026, 11, 7, 23, 30, tzinfo=tiempo.BOGOTA)
    )
    assert _cosecha(d, "2026-11-07", 5)["harvested_at"] == "2026-11-07"
    with pytest.raises(ReglaNegocio):
        _cosecha(d, "2026-11-08", 5)
    assert stats_service._local_date("2026-11-08T04:30:00Z").isoformat() == "2026-11-07"


def test_totales_no_mezclan_monedas(bd, d):
    _cosecha(d, "2026-10-01", 100, 9000, "COP")
    _cosecha(d, "2026-10-02", 50, 2, "USD")
    _cosecha(d, "2026-10-03", 10)
    lista = correr(cosecha_service.listar(USUARIO_A, LOTE_A, None, None, 50, 0))
    totales = lista["totals"]
    assert totales["quantity_kg"] == 160
    assert totales["by_currency"] == [
        {"currency": "COP", "revenue": 900000, "harvests_with_price": 1},
        {"currency": "USD", "revenue": 100, "harvests_with_price": 1},
    ]
    assert totales["harvests_without_price"] == 1
    assert [i["harvested_at"] for i in lista["items"]] == ["2026-10-03", "2026-10-02", "2026-10-01"]


def test_cosecha_avisa_estimaciones_afectadas(bd, d):
    est = correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-05-01", "2026-10-31")))
    respuesta = _cosecha(d, "2026-06-15", 40)
    assert respuesta["affects_estimations"] == [est["id"]]
    assert _cosecha(d, "2026-11-01", 40)["affects_estimations"] == []


# ---------------- Pérdida estimada ----------------

def test_cosechas_en_los_limites_del_periodo_se_incluyen(bd, d):
    _cosecha(d, "2026-05-01", 400)
    _cosecha(d, "2026-10-31", 500)
    _cosecha(d, "2026-11-01", 999)  # fuera del periodo
    r = correr(perdida_service.preview(USUARIO_A, LOTE_A, _estimacion(d, "2026-05-01", "2026-10-31")))
    assert r["harvested_kg"] == 900 and r["lost_kg"] == 300 and r["loss_pct"] == 25
    assert r["estimated_loss_amount"] == 2700000 and r["harvests_in_period"] == 2
    assert r["id"] is None and r["warnings"] == []


def test_avisos_sin_cosechas_y_periodo_futuro(bd, d):
    r = correr(perdida_service.preview(USUARIO_A, LOTE_A, _estimacion(d, "2026-10-01", "2026-12-31")))
    assert r["harvested_kg"] == 0
    assert perdida_service.AVISO_FUTURO in r["warnings"]
    assert perdida_service.AVISO_SIN_COSECHAS in r["warnings"]


def test_traslape_rechazado_y_editar_no_choca_consigo_misma(bd, d):
    est = correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-01-01", "2026-03-31")))
    with pytest.raises(ReglaNegocio) as error:
        correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-03-31", "2026-05-31")))
    assert error.value.status == 422
    assert "01/01/2026 – 31/03/2026" in error.value.mensaje
    editada = correr(perdida_service.actualizar(USUARIO_A, est["id"], {"price_per_kg": Decimal(10000)}))
    assert editada["estimated_loss_amount"] == 12000000  # 1200 kg perdidos × 10.000


def test_preview_al_editar_no_choca_consigo_misma(bd, d):
    datos = _estimacion(d, "2026-11-07", "2026-11-07", esperado=10, precio=10000)
    est = correr(perdida_service.crear(USUARIO_A, LOTE_A, datos))
    with pytest.raises(ReglaNegocio) as error:  # sin excluir: es un traslape real
        correr(perdida_service.preview(USUARIO_A, LOTE_A, datos))
    assert error.value.status == 422
    r = correr(perdida_service.preview(USUARIO_A, LOTE_A, datos, est["id"]))
    assert r["lost_kg"] == 10 and r["id"] is None
    with pytest.raises(ReglaNegocio) as error:  # no se puede excluir una estimación ajena
        correr(perdida_service.preview(USUARIO_B, "plot-b", datos, est["id"]))
    assert error.value.status == 404


def test_rango_maximo_dos_anios(bd, d):
    with pytest.raises(ReglaNegocio):
        correr(perdida_service.preview(USUARIO_A, LOTE_A, _estimacion(d, "2023-01-01", "2025-01-02")))


def test_editar_recalcula_con_cosechas_actuales(bd, d):
    est = correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-01-01", "2026-06-30")))
    assert est["harvested_kg"] == 0
    _cosecha(d, "2026-03-10", 1000)
    editada = correr(perdida_service.actualizar(USUARIO_A, est["id"], {}))
    assert editada["harvested_kg"] == 1000 and editada["lost_kg"] == 200
    guardada = bd.losses[est["id"]]
    assert guardada["source"] == "RULES" and guardada["created_by"] == USUARIO_A
    assert guardada["inputs"]["lost_kg"] == 200


def test_defaults(bd, d):
    vacio = correr(perdida_service.defaults(USUARIO_A, LOTE_A))
    assert vacio["expected_yield_kg"] == 1200  # 600 kg/ha × 2 ha
    assert vacio["price_per_kg"] is None and vacio["currency"] == "COP"
    assert vacio["period_from"] == "2024-01-15"  # siembra
    assert vacio["period_to"] == "2026-11-07"
    _cosecha(d, "2026-10-01", 10, 8500)
    correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-01-01", "2026-06-30")))
    lleno = correr(perdida_service.defaults(USUARIO_A, LOTE_A))
    assert lleno["price_per_kg"] == 8500 and lleno["price_source"] == "última cosecha"
    assert lleno["period_from"] == "2026-07-01"


def test_registros_antiguos_se_leen_desde_inputs(bd):
    bd.losses["vieja"] = {
        "id": "vieja", "plot_id": LOTE_A, "created_at": "2026-02-01T10:00:00+00:00",
        "expected_yield_kg": "100", "price_per_kg": "5", "estimated_loss_amount": "250",
        "currency": "COP ", "source": "RULES", "explanation": None,
        "inputs": {"lost_kg": 50, "loss_pct": 50, "period_from": "2026-01-01",
                   "period_to": "2026-01-31"},
    }
    r = correr(perdida_service.obtener(USUARIO_A, "vieja"))
    assert r["lost_kg"] == 50 and r["period_to"] == "2026-01-31" and r["currency"] == "COP"


# ---------------- Seguridad ----------------

def test_usuario_b_no_accede_a_datos_de_a(bd, d):
    cosecha = _cosecha(d, "2026-10-01", 10)
    est = correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-01-01", "2026-06-30")))
    intentos = [
        cosecha_service.obtener(USUARIO_B, cosecha["id"]),
        cosecha_service.actualizar(USUARIO_B, cosecha["id"], {"quantity_kg": Decimal(1)}),
        cosecha_service.eliminar(USUARIO_B, cosecha["id"]),
        cosecha_service.listar(USUARIO_B, LOTE_A, None, None, 50, 0),
        perdida_service.obtener(USUARIO_B, est["id"]),
        perdida_service.actualizar(USUARIO_B, est["id"], {}),
        perdida_service.eliminar(USUARIO_B, est["id"]),
        perdida_service.defaults(USUARIO_B, LOTE_A),
    ]
    for intento in intentos:
        with pytest.raises(ReglaNegocio) as error:
            correr(intento)
        assert error.value.status == 404
    assert cosecha["id"] in bd.harvests and est["id"] in bd.losses


# ---------------- Estadísticas ----------------

def _stats(d, desde="2026-05-08", hasta="2026-11-07"):
    return correr(stats_service.obtener(USUARIO_A, LOTE_A, d(desde), d(hasta), "month"))


def test_stats_lote_vacio_no_falla(bd, d):
    s = _stats(d)
    assert s["currency"] == "COP" and s["mixed_currency"] is False
    assert s["expected_vs_harvested"] == [] and s["totals"]["loss_pct_overall"] is None
    assert all(p["kg"] == 0 for p in s["harvest_series"])


def test_stats_refleja_cosechas_y_estimaciones(bd, d):
    _cosecha(d, "2026-06-10", 900, 9000)
    est = correr(perdida_service.crear(USUARIO_A, LOTE_A, _estimacion(d, "2026-05-08", "2026-09-30")))
    s = _stats(d)
    assert s["totals"]["harvested_kg"] == 900 and s["totals"]["revenue"] == 8100000
    assert s["totals"]["expected_kg"] == 1200 and s["totals"]["lost_kg"] == 300
    assert s["totals"]["loss_pct_overall"] == 25
    septiembre = next(p for p in s["expected_vs_harvested"] if p["period"] == "2026-09")
    assert septiembre["expected_kg"] == 1200
    assert s["loss_series"][-1]["cumulative_loss_amount"] == 2700000

    correr(perdida_service.actualizar(USUARIO_A, est["id"], {"expected_yield_kg": Decimal(1000)}))
    assert _stats(d)["totals"]["lost_kg"] == 100


def test_stats_dos_monedas(bd, d):
    _cosecha(d, "2026-06-10", 100, 9000, "COP")
    _cosecha(d, "2026-07-10", 100, 9000, "COP")
    _cosecha(d, "2026-08-10", 50, 2, "USD")
    s = _stats(d)
    assert s["currency"] == "COP" and s["mixed_currency"] is True
    assert s["excluded_other_currency"] == {"count": 1, "currency": "USD"}
    assert s["totals"]["revenue"] == 1800000
    assert s["totals"]["harvested_kg"] == 250  # los kilos sí se suman
