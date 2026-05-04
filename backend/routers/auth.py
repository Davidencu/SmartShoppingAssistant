import base64
import json
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from core.config import settings
from models.user import (
    EmailCheckRequest,
    MagicLinkVerifyRequest,
    OTPRequest,
    OTPVerifyRequest,
    PasskeyChallengeRequest,
    PasskeyRegisterRequest,
    PasskeyVerifyRequest,
)
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/auth", tags=["auth"])
_bearer = HTTPBearer()

# In-memory stores (keyed by email). Replace with Redis in production.
_challenges: dict[str, bytes] = {}
_registration_data: dict[str, dict] = {}


def _b64url_encode(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def create_token(user_id: str, email: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.now(timezone.utc) + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    try:
        payload = jwt.decode(
            credentials.credentials, settings.jwt_secret, algorithms=["HS256"]
        )
        return {"user_id": payload["sub"], "email": payload["email"]}
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.post("/check-email")
async def check_email(req: EmailCheckRequest):
    supabase = get_supabase_admin()
    result = supabase.table("profiles").select("id").eq("email", req.email).execute()
    return {"exists": len(result.data) > 0}


@router.post("/send-otp")
async def send_otp(req: OTPRequest):
    supabase = get_supabase_admin()
    result = supabase.table("profiles").select("id").eq("email", req.email).execute()
    if result.data:
        raise HTTPException(status_code=409, detail="Email already registered")

    _registration_data[req.email] = {
        "phone": req.phone,
        "street_address": req.street_address,
        "city": req.city,
        "state": req.state,
        "postal_code": req.postal_code,
        "country": req.country,
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.supabase_url}/auth/v1/otp",
            json={"email": req.email, "create_user": True},
            headers={
                "apikey": settings.supabase_service_role_key,
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "Content-Type": "application/json",
            },
        )
    print(resp.status_code, resp.text)
    if resp.status_code not in (200, 204):
        raise HTTPException(status_code=500, detail="Failed to send confirmation email")

    return {"message": "OTP sent to your email"}


@router.post("/verify-otp")
async def verify_otp(req: OTPVerifyRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{settings.supabase_url}/auth/v1/verify",
            json={"type": "email", "email": req.email, "token": req.otp},
            headers={
                "apikey": settings.supabase_anon_key,
                "Content-Type": "application/json",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP")

    data = resp.json()
    user_id: str = data["user"]["id"]

    reg = _registration_data.get(req.email)
    if not reg:
        raise HTTPException(status_code=400, detail="Registration session expired, please start again")

    supabase = get_supabase_admin()
    supabase.table("profiles").insert(
        {
            "id": user_id,
            "email": req.email,
            "phone": reg["phone"],
            "street_address": reg["street_address"],
            "city": reg["city"],
            "state": reg.get("state"),
            "postal_code": reg["postal_code"],
            "country": reg["country"],
        }
    ).execute()
    options = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_id=user_id.encode(),
        user_name=req.email,
        user_display_name=req.email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _challenges[req.email] = options.challenge

    return {
        "user_id": user_id,
        "options": json.loads(options_to_json(options)),
    }


@router.post("/passkey/register")
async def passkey_register(req: PasskeyRegisterRequest):
    challenge = _challenges.get(req.email)
    if not challenge:
        raise HTTPException(status_code=400, detail="No pending registration challenge")

    reg = _registration_data.get(req.email)
    if not reg or "user_id" not in reg:
        raise HTTPException(status_code=400, detail="Registration session expired. Please register again.")
    user_id = reg["user_id"]

    try:
        verification = verify_registration_response(
            credential=req.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.frontend_origin,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Passkey registration failed: {exc}")

    supabase = get_supabase_admin()
    supabase.table("profiles").insert(
        {
            "id": user_id,
            "email": req.email,
            "phone": reg["phone"],
            "street_address": reg["street_address"],
            "city": reg["city"],
            "state": reg.get("state"),
            "postal_code": reg["postal_code"],
            "country": reg["country"],
        }
    ).execute()
    supabase.table("passkeys").insert(
        {
            "user_id": user_id,
            "email": req.email,
            "credential_id": _b64url_encode(verification.credential_id),
            "public_key": _b64url_encode(verification.credential_public_key),
            "sign_count": verification.sign_count,
        }
    ).execute()

    _challenges.pop(req.email, None)
    _registration_data.pop(req.email, None)

    return {"token": create_token(user_id, req.email)}


@router.post("/passkey/challenge")
async def passkey_challenge(req: PasskeyChallengeRequest):
    supabase = get_supabase_admin()
    profile = supabase.table("profiles").select("id").eq("email", req.email).execute()
    if not profile.data:
        raise HTTPException(status_code=404, detail="User not found")

    passkey_row = (
        supabase.table("passkeys")
        .select("credential_id")
        .eq("email", req.email)
        .execute()
    )
    if not passkey_row.data:
        raise HTTPException(status_code=404, detail="No passkey registered for this user")

    credential_id_bytes = _b64url_decode(passkey_row.data[0]["credential_id"])
    options = generate_authentication_options(
        rp_id=settings.rp_id,
        allow_credentials=[PublicKeyCredentialDescriptor(id=credential_id_bytes)],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    _challenges[req.email] = options.challenge

    return {"options": json.loads(options_to_json(options))}


@router.post("/passkey/verify")
async def passkey_verify(req: PasskeyVerifyRequest):
    challenge = _challenges.get(req.email)
    if not challenge:
        raise HTTPException(status_code=400, detail="No pending authentication challenge")

    supabase = get_supabase_admin()
    passkey_row = (
        supabase.table("passkeys")
        .select("user_id, credential_id, public_key, sign_count")
        .eq("email", req.email)
        .execute()
    )
    if not passkey_row.data:
        raise HTTPException(status_code=404, detail="No passkey registered for this user")

    row = passkey_row.data[0]
    stored_public_key = _b64url_decode(row["public_key"])
    current_sign_count = row["sign_count"]
    user_id = row["user_id"]

    try:
        verification = verify_authentication_response(
            credential=req.credential,
            expected_challenge=challenge,
            expected_rp_id=settings.rp_id,
            expected_origin=settings.frontend_origin,
            credential_public_key=stored_public_key,
            credential_current_sign_count=current_sign_count,
            require_user_verification=True,
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"Passkey verification failed: {exc}")

    supabase.table("passkeys").update({"sign_count": verification.new_sign_count}).eq(
        "email", req.email
    ).execute()
    _challenges.pop(req.email, None)

    return {"token": create_token(user_id, req.email)}


@router.post("/verify-magic")
async def verify_magic(req: MagicLinkVerifyRequest):
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{settings.supabase_url}/auth/v1/user",
            headers={
                "apikey": settings.supabase_anon_key,
                "Authorization": f"Bearer {req.access_token}",
            },
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired magic link token")

    user_data = resp.json()
    user_id: str = user_data["id"]
    email: str = user_data["email"]

    reg = _registration_data.get(email)
    if not reg:
        raise HTTPException(
            status_code=400,
            detail="Registration session expired. Please register again.",
        )

    reg["user_id"] = user_id

    options = generate_registration_options(
        rp_id=settings.rp_id,
        rp_name=settings.rp_name,
        user_id=user_id.encode(),
        user_name=email,
        user_display_name=email,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )
    _challenges[email] = options.challenge

    return {
        "user_id": user_id,
        "email": email,
        "options": json.loads(options_to_json(options)),
    }
