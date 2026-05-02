from pydantic import BaseModel, computed_field
from uuid import UUID
from datetime import datetime
from enum import Enum


class TransactionType(str, Enum):
    TOPUP = "TOPUP"
    FREEZE = "FREEZE"
    DEDUCT = "DEDUCT"
    REFUND = "REFUND"


class Wallet(BaseModel):
    id: UUID
    user_id: UUID
    balance_cents: int
    frozen_cents: int
    currency: str
    updated_at: datetime

    @computed_field
    @property
    def available_cents(self) -> int:
        return self.balance_cents - self.frozen_cents


class WalletTransaction(BaseModel):
    id: UUID
    wallet_id: UUID
    type: TransactionType
    amount_cents: int
    reference_id: str | None
    order_id: UUID | None
    created_at: datetime


class WalletResponse(BaseModel):
    wallet: Wallet
    recent_transactions: list[WalletTransaction]


class LemonSqueezyMeta(BaseModel):
    event_name: str
    custom_data: dict | None = None


class LemonSqueezyWebhookPayload(BaseModel):
    meta: LemonSqueezyMeta
    data: dict
