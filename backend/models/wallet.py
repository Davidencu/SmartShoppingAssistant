from typing import Literal

from pydantic import BaseModel


class WalletBalance(BaseModel):
    balance: float
    currency: str = "USD"


class TopUpRequest(BaseModel):
    amount: Literal[10, 25, 40, 50, 80, 100]


class CheckoutResponse(BaseModel):
    checkout_url: str
