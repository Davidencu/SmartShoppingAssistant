from pydantic import BaseModel, Field, field_validator
from uuid import UUID
from datetime import datetime
import re


class Address(BaseModel):
    recipient_name: str = Field(..., min_length=2, max_length=100)
    street: str = Field(..., min_length=3, max_length=200)
    city: str = Field(..., min_length=2, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str = Field(default="RO", min_length=2, max_length=3)
    zip_code: str = Field(..., min_length=3, max_length=10)


class ProfileCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=100)
    phone: str = Field(..., max_length=20)
    address: Address

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        clean = re.sub(r"[\s\-\(\)]", "", v)
        if not re.match(r"^\+?[1-9]\d{6,14}$", clean):
            raise ValueError("Invalid phone number — use international format, e.g. +40712345678")
        return clean


class UserProfile(BaseModel):
    id: UUID
    full_name: str
    phone: str
    created_at: datetime


class UserAddress(BaseModel):
    id: UUID
    user_id: UUID
    recipient_name: str
    street: str
    city: str
    state: str | None
    country: str
    zip_code: str
    is_default: bool
    created_at: datetime


class ProfileResponse(BaseModel):
    profile: UserProfile
    address: UserAddress
