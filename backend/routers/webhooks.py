import hashlib
import hmac
import json

from fastapi import APIRouter, HTTPException, Request

from core.config import settings
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/lemonsqueezy")
async def lemonsqueezy_webhook(request: Request):
    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    expected = hmac.new(
        settings.lemonsqueezy_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = json.loads(body)
    event_name: str = payload.get("meta", {}).get("event_name", "")

    if event_name in ("order_created", "subscription_created"):
        custom_data = payload.get("meta", {}).get("custom_data", {})
        user_id = custom_data.get("user_id")
        if not user_id:
            raise HTTPException(status_code=400, detail="Missing user_id in webhook payload")

        supabase = get_supabase_admin()
        supabase.table("profiles").update({"plan": "pro"}).eq("id", user_id).execute()

    return {"message": "ok"}
