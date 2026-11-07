from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi.concurrency import run_in_threadpool as hilo

from app import config
from app.core.exceptions import ReglaNegocio
from app.repository import cosecha_perdida_repository
from app.repository import plot_modules_repository as repo
from app.services.perdidas_calculo import dec, normalizar_estimacion, redondear_kg, redondear_monto

_BOGOTA = ZoneInfo("America/Bogota")


def _local_date(value: str | datetime | date) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=_BOGOTA)
    return parsed.astimezone(_BOGOTA).date()


def _code(diagnostic: dict) -> str | None:
    prediction = diagnostic.get("ai_prediction") or {}
    code = diagnostic.get("predicted_label") or prediction.get("disease_code")
    if code:
        return code
    top = prediction.get("top") or []
    if top and float(top[0].get("confidence") or 0) >= config.MODEL_CONFIG["umbral"]:
        return top[0].get("disease_code")
    return None


def _periods(start: date, end: date, granularity: str) -> list[str]:
    key = lambda d: d.strftime("%Y-%m") if granularity == "month" else (
        f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
    )
    current = start
    output = []
    while current <= end:
        value = key(current)
        if not output or output[-1] != value:
            output.append(value)
        current += timedelta(days=1)
    return output


def _period_key(value: str | datetime | date, granularity: str) -> str:
    d = _local_date(value)
    return d.strftime("%Y-%m") if granularity == "month" else (
        f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
    )


def _status(incidence: float, alert: float, danger: float) -> str:
    if incidence >= danger:
        return "peligro"
    if incidence >= alert:
        return "alerta"
    return "sano"


async def obtener(
    user_id: str, plot_id: str, desde: date, hasta: date, granularidad: str
) -> dict:
    if desde > hasta:
        raise ReglaNegocio(400, "La fecha inicial debe ser anterior a la final.")
    try:
        max_end = desde.replace(year=desde.year + 3)
    except ValueError:
        max_end = desde.replace(year=desde.year + 3, day=28)
    if hasta > max_end:
        raise ReglaNegocio(400, "El periodo no puede superar 3 años.")
    plot = await hilo(repo.lote_propietario, user_id, plot_id)
    threshold = plot["crop"]["crop_type"]
    samples, harvests, losses, care = await _fetch_series(plot_id, desde, hasta)
    diagnostics = await _diagnostics(user_id, samples, desde, hasta)

    periods = _periods(desde, hasta, granularidad)
    incidence_series = []
    health = []
    for sample in samples:
        evaluated = int(sample["plants_evaluated"])
        affected = int(sample["plants_affected"])
        incidence = sample.get("incidence_pct")
        incidence = float(incidence) if incidence is not None else round(affected * 100 / evaluated, 2)
        status = _status(incidence, float(threshold["alert_threshold_pct"]), float(threshold["danger_threshold_pct"]))
        incidence_series.append({
            "sampled_at": sample["sampled_at"], "incidence_pct": incidence,
            "plants_evaluated": evaluated, "plants_affected": affected,
            "status": status, "sample_id": sample["id"],
        })
        health.append({"date": _local_date(sample["sampled_at"]).isoformat(), "status": status})
    incidence_series.sort(key=lambda item: item["sampled_at"])

    disease_counts: Counter[str] = Counter()
    disease_periods: dict[tuple[str, str], int] = defaultdict(int)
    for diagnostic in diagnostics:
        code = _code(diagnostic)
        if not code or code == config.CODIGO_SANO:
            continue
        disease_counts[code] += 1
        disease_periods[(_period_key(diagnostic["created_at"], granularidad), code)] += 1
    total_disease = sum(disease_counts.values())
    disease_breakdown = [
        {
            "disease_code": code,
            "disease_name": config.ENFERMEDADES.get(code, {}).get("name", code),
            "count": count,
            "pct": round(count * 100 / total_disease, 2) if total_disease else 0,
        }
        for code, count in disease_counts.most_common()
    ]
    disease_over_time = [
        {"period": period, "disease_code": code, "count": disease_periods[(period, code)]}
        for period in periods for code in disease_counts
    ]
    money = _money_series(harvests, losses, periods, granularidad)
    incidences = [item["incidence_pct"] for item in incidence_series]
    return {
        "plot_id": plot_id,
        "period": {"from": desde.isoformat(), "to": hasta.isoformat()},
        "thresholds": {
            "alert_pct": float(threshold["alert_threshold_pct"]),
            "danger_pct": float(threshold["danger_threshold_pct"]),
        },
        "incidence_series": incidence_series,
        "health_evolution": health,
        "disease_breakdown": disease_breakdown,
        "disease_over_time": disease_over_time,
        "harvest_series": money["harvest_series"],
        "loss_series": money["loss_series"],
        "income_series": money["income_series"],
        "expected_vs_harvested": money["expected_vs_harvested"],
        "harvests_without_price": money["harvests_without_price"],
        "currency": money["currency"],
        "mixed_currency": money["mixed_currency"],
        "excluded_other_currency": money["excluded_other_currency"],
        "totals": {
            "samples": len(samples),
            "avg_incidence_pct": round(sum(incidences) / len(incidences), 2) if incidences else 0,
            "max_incidence_pct": max(incidences, default=0),
            **money["totals"],
            "care_cost_cop": sum(float(item.get("cost") or 0) for item in care),
        },
    }


async def _fetch_series(plot_id: str, start: date, end: date):
    import asyncio
    samples, harvests, estimations, care = await asyncio.gather(
        hilo(repo.muestreos, plot_id, start, end),
        hilo(repo.cosechas, plot_id, start, end),
        hilo(cosecha_perdida_repository.estimaciones, plot_id),
        hilo(repo.cuidados, plot_id, start, end),
    )
    return samples, harvests, estimaciones_del_rango(estimations, start, end), care


def estimaciones_del_rango(rows: list[dict], start: date, end: date) -> list[dict]:
    """Estimaciones (normalizadas) cuyo `period_to` cae en el rango, por fecha de fin."""
    normalized = [normalizar_estimacion(row) for row in rows]
    selected = [e for e in normalized if e["period_to"] and start <= e["period_to"] <= end]
    return sorted(selected, key=lambda e: e["period_to"])


def _currency(row: dict) -> str:
    return (row.get("currency") or "COP").strip()


def _money_series(
    harvests: list[dict], losses: list[dict], periods: list[str], granularidad: str
) -> dict:
    """Series de kilos y dinero. Los montos de una moneda distinta a la dominante
    se excluyen (nunca se suman ni se convierten)."""
    monetary = [_currency(h) for h in harvests if h.get("price_per_kg") is not None]
    monetary += [e["currency"] for e in losses if e["estimated_loss_amount"] is not None]
    counts = Counter(monetary)
    currency = max(counts, key=lambda c: (counts[c], c == "COP")) if counts else "COP"
    others = {c: n for c, n in counts.items() if c != currency}

    zero = Decimal(0)
    harvested_by: dict[str, Decimal] = defaultdict(Decimal)
    revenue_by: dict[str, Decimal] = defaultdict(Decimal)
    without_price = 0
    for row in harvests:
        period = _period_key(row["harvested_at"], granularidad)
        kg = dec(row["quantity_kg"])
        harvested_by[period] += kg
        price = dec(row.get("price_per_kg"))
        if price is None:
            without_price += 1
        elif _currency(row) == currency:
            revenue_by[period] += kg * price

    expected_by: dict[str, Decimal] = defaultdict(Decimal)
    lost_by: dict[str, Decimal] = defaultdict(Decimal)
    loss_amount_by: dict[str, Decimal] = defaultdict(Decimal)
    for e in losses:
        period = _period_key(e["period_to"], granularidad)
        expected_by[period] += e["expected_yield_kg"] or zero
        lost_by[period] += e["lost_kg"] or zero
        if e["currency"] == currency and e["estimated_loss_amount"] is not None:
            loss_amount_by[period] += e["estimated_loss_amount"]

    def money(value: Decimal) -> float:
        return float(redondear_monto(value, currency))

    harvest_series, income_series, loss_series, expected_vs = [], [], [], []
    income_total = loss_total = zero
    for period in periods:
        income_total += revenue_by[period]
        loss_total += loss_amount_by[period]
        harvest_series.append({
            "period": period, "kg": float(redondear_kg(harvested_by[period])),
            "revenue": money(revenue_by[period]),
        })
        income_series.append({
            "period": period, "revenue": money(revenue_by[period]),
            "cumulative_revenue": money(income_total),
        })
        loss_series.append({
            "period": period, "lost_kg": float(redondear_kg(lost_by[period])),
            "loss_amount": money(loss_amount_by[period]),
            "cumulative_loss_amount": money(loss_total),
        })
        if losses:
            expected_vs.append({
                "period": period, "expected_kg": float(redondear_kg(expected_by[period])),
                "harvested_kg": float(redondear_kg(harvested_by[period])),
            })

    expected_total = sum(expected_by.values(), zero)
    lost_total = sum(lost_by.values(), zero)
    return {
        "currency": currency,
        "mixed_currency": len(counts) > 1,
        "excluded_other_currency": (
            {"count": sum(others.values()), "currency": max(others, key=others.get)}
            if others else None
        ),
        "harvest_series": harvest_series,
        "income_series": income_series,
        "loss_series": loss_series,
        "expected_vs_harvested": expected_vs,
        "harvests_without_price": without_price,
        "totals": {
            "harvested_kg": float(redondear_kg(sum(harvested_by.values(), zero))),
            "revenue": money(income_total),
            "loss_amount": money(loss_total),
            "expected_kg": float(redondear_kg(expected_total)),
            "lost_kg": float(redondear_kg(lost_total)),
            "loss_pct_overall": (
                float(redondear_kg(lost_total / expected_total * 100)) if expected_total else None
            ),
        },
    }


async def _diagnostics(
    user_id: str, samples: list[dict], desde: date, hasta: date
) -> list[dict]:
    ids = [sample["id"] for sample in samples]
    return await hilo(repo.diagnosticos, user_id, ids, desde, hasta)
