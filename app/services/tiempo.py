from datetime import date, datetime
from zoneinfo import ZoneInfo

BOGOTA = ZoneInfo("America/Bogota")


def ahora() -> datetime:
    return datetime.now(BOGOTA)


def hoy() -> date:
    """Fecha actual en Colombia (las pruebas reemplazan `ahora`)."""
    return ahora().date()
