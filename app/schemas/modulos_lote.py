from datetime import date
from typing import Literal

from pydantic import BaseModel, model_validator


class InformePeriodo(BaseModel):
    period_from: date
    period_to: date

    @model_validator(mode="after")
    def validar_periodo(self):
        if self.period_to < self.period_from:
            raise ValueError("La fecha final debe ser igual o posterior a la inicial.")
        return self


Granularidad = Literal["week", "month"]
TipoEvento = Literal["sample", "diagnosis", "care", "harvest", "loss", "report"]
