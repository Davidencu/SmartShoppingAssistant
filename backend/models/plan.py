from typing import Literal

from pydantic import BaseModel


class PlanStatus(BaseModel):
    plan: str
    checkout_credits: int


class PlanSelectRequest(BaseModel):
    plan: Literal["free"]


class PlanCheckoutResponse(BaseModel):
    checkout_url: str
