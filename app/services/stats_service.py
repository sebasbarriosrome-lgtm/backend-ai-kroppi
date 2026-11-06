from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.concurrency import run_in_threadpool as hilo

from app import config
from app.core.exceptions import ReglaNegocio
from app.repository import plot_modules_repository as repo

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
    harvest_by_period: dict[str, dict] = defaultdict(lambda: {"kg": 0.0, "revenue_cop": 0.0})
    harvests_without_price = 0
    revenue = 0.0
    harvested = 0.0
    for row in harvests:
        period = _period_key(row["harvested_at"], granularidad)
        quantity = float(row["quantity_kg"])
        harvested += quantity
        harvest_by_period[period]["kg"] += quantity
        if row.get("price_per_kg") is None:
            harvests_without_price += 1
        else:
            value = quantity * float(row["price_per_kg"])
            revenue += value
            harvest_by_period[period]["revenue_cop"] += value
    harvest_series = [
        {"period": period, **harvest_by_period[period]}
        for period in periods
    ]

    loss_by_period: dict[str, dict] = defaultdict(lambda: {"lost_kg": 0.0, "loss_amount_cop": 0.0})
    loss_amount = 0.0
    for row in losses:
        inputs = row.get("inputs") or {}
        period = _period_key(row["created_at"], granularidad)
        amount = float(row.get("estimated_loss_amount") or 0)
        lost = float(inputs.get("lost_kg") or 0)
        loss_by_period[period]["lost_kg"] += lost
        loss_by_period[period]["loss_amount_cop"] += amount
        loss_amount += amount
    loss_series = []
    cumulative = 0.0
    for period in periods:
        values = loss_by_period[period]
        cumulative += values["loss_amount_cop"]
        loss_series.append({
            "period": period, **values,
            "cumulative_loss_amount_cop": cumulative,
        })
    income_cumulative = 0.0
    income_series = []
    for period in periods:
        values = harvest_by_period[period]["revenue_cop"]
        income_cumulative += values
        income_series.append({
            "period": period, "revenue_cop": values,
            "cumulative_revenue_cop": income_cumulative,
        })

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
        "harvest_series": harvest_series,
        "loss_series": loss_series,
        "income_series": income_series,
        "harvests_without_price": harvests_without_price,
        "totals": {
            "samples": len(samples),
            "avg_incidence_pct": round(sum(incidences) / len(incidences), 2) if incidences else 0,
            "max_incidence_pct": max(incidences, default=0),
            "harvested_kg": harvested,
            "revenue_cop": revenue,
            "loss_amount_cop": loss_amount,
            "care_cost_cop": sum(float(item.get("cost") or 0) for item in care),
        },
    }


async def _fetch_series(plot_id: str, start: date, end: date):
    import asyncio
    return await asyncio.gather(
        hilo(repo.muestreos, plot_id, start, end),
        hilo(repo.cosechas, plot_id, start, end),
        hilo(repo.perdidas, plot_id, start, end),
        hilo(repo.cuidados, plot_id, start, end),
    )


async def _diagnostics(
    user_id: str, samples: list[dict], desde: date, hasta: date
) -> list[dict]:
    ids = [sample["id"] for sample in samples]
    return await hilo(repo.diagnosticos, user_id, ids, desde, hasta)
