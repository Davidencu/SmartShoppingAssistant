import httpx
from fastapi import APIRouter, Depends, HTTPException

from core.config import settings
from models.wallet import CheckoutResponse, TopUpRequest, WalletBalance
from routers.auth import get_current_user
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/wallet", tags=["wallet"])

_ls_store_id: str | None = None


async def _get_store_id() -> str:
    global _ls_store_id
    if _ls_store_id:
        return _ls_store_id

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.lemonsqueezy.com/v1/variants/{settings.lemonsqueezy_variant_id}",
            headers={"Authorization": f"Bearer {settings.lemonsqueezy_api_key}"},
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=500, detail="Failed to fetch LemonSqueezy store info")

    _ls_store_id = resp.json()["data"]["relationships"]["store"]["data"]["id"]
    return _ls_store_id


@router.get("/balance", response_model=WalletBalance)
async def get_balance(user: dict = Depends(get_current_user)):
    supabase = get_supabase_admin()
    result = (
        supabase.table("wallets")
        .select("balance, currency")
        .eq("user_id", user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Wallet not found")
    row = result.data[0]
    return WalletBalance(balance=float(row["balance"]), currency=row["currency"])


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(req: TopUpRequest, user: dict = Depends(get_current_user)):
    store_id = await _get_store_id()

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.lemonsqueezy.com/v1/checkouts",
            json={
                "data": {
                    "type": "checkouts",
                    "attributes": {
                        "custom_price": req.amount * 100,
                        "checkout_data": {
                            "custom": {"user_id": user["user_id"]}
                        },
                        "product_options": {
                            "redirect_url": f"{settings.frontend_origin}/dashboard"
                        },
                    },
                    "relationships": {
                        "store": {
                            "data": {"type": "stores", "id": str(store_id)}
                        },
                        "variant": {
                            "data": {
                                "type": "variants",
                                "id": str(settings.lemonsqueezy_variant_id),
                            }
                        },
                    },
                }
            },
            headers={
                "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
                "Content-Type": "application/vnd.api+json",
                "Accept": "application/vnd.api+json",
            },
        )

    if resp.status_code not in (200, 201):
        raise HTTPException(status_code=500, detail="Failed to create checkout session")

    checkout_url: str = resp.json()["data"]["attributes"]["url"]
    return CheckoutResponse(checkout_url=checkout_url)
