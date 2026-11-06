from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Latitud = Annotated[float, Field(ge=-90, le=90)]
Longitud = Annotated[float, Field(ge=-180, le=180)]

EstadoSalud = Literal["HEALTHY", "ALERT", "DANGER"]
MetodoMuestreo = Literal["SAMPLING", "ESTIMATION"]


class OutBase(BaseModel):
    """Base para respuestas: permite construir el schema desde un modelo SQLAlchemy."""

    model_config = ConfigDict(from_attributes=True)
