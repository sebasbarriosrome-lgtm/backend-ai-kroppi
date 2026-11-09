from typing import Literal

from pydantic import BaseModel, ConfigDict


class PagoCrearOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str
    amount_in_cents: Literal[1_990_000]
    currency: Literal["COP"]
    public_key: str
    signature: str
    checkout_url: str
