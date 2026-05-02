import hashlib
import hmac
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status

from core.config import get_settings
from services.supabase_service import SupabaseService

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_TOPUP_EVENT = "order_created"


def _verify_lemonsqueezy_signature(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/lemonsqueezy", status_code=status.HTTP_200_OK)
async def lemonsqueezy_webhook(request: Request) -> dict:
    settings = get_settings()
    raw_body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not _verify_lemonsqueezy_signature(raw_body, signature, settings.lemonsqueezy_webhook_secret):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    payload = json.loads(raw_body)
    event_name = payload.get("meta", {}).get("event_name", "")

    if event_name != _TOPUP_EVENT:
        return {"status": "ignored"}

    custom_data = payload.get("meta", {}).get("custom_data", {})
    user_id_str = custom_data.get("user_id")
    if not user_id_str:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing user_id in custom_data")

    try:
        user_id = UUID(user_id_str)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid user_id format")

    attributes = payload.get("data", {}).get("attributes", {})
    total_cents = int(round(float(attributes.get("total", 0)) * 100))
    if total_cents <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid amount")

    order_id = str(payload.get("data", {}).get("id", ""))
    SupabaseService().credit_wallet(user_id, total_cents, reference_id=order_id)

    return {"status": "credited"}
