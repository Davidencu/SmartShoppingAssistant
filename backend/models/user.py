import re
from typing import Optional

from pydantic import BaseModel, field_validator


class EmailCheckRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError("Invalid email format")
        return v.lower()


class OTPRequest(BaseModel):
    email: str
    phone: str
    city: str
    state: Optional[str] = None
    country: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$", v):
            raise ValueError("Invalid email format")
        return v.lower()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        if not re.match(r"^\+[1-9]\d{6,14}$", v):
            raise ValueError("Phone must be in E.164 format: +CountryCode followed by digits")
        return v


class OTPVerifyRequest(BaseModel):
    email: str
    otp: str


class PasskeyRegisterRequest(BaseModel):
    email: str
    credential: dict


class PasskeyChallengeRequest(BaseModel):
    email: str


class PasskeyVerifyRequest(BaseModel):
    email: str
    credential: dict


class MagicLinkVerifyRequest(BaseModel):
    access_token: str
