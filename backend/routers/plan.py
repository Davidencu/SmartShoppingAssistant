import httpx
from fastapi import APIRouter, Depends, HTTPException

from core.config import settings
from models.plan import PlanCheckoutResponse, PlanSelectRequest, PlanStatus
from routers.auth import get_current_user
from services.supabase_service import get_supabase_admin

router = APIRouter(prefix="/plan", tags=["plan"])

_ls_store_id: str | None = None


async def _get_store_id() -> str:
    global _ls_store_id
    if _ls_store_id:
        return _ls_store_id
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            "https://api.lemonsqueezy.com/v1/stores",
            headers={"Authorization": f"Bearer {settings.lemonsqueezy_api_key}"},
        )
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail="Failed to fetch LemonSqueezy store")
    stores = resp.json().get("data", [])
    if not stores:
        raise HTTPException(status_code=502, detail="No LemonSqueezy store found")
    _ls_store_id = stores[0]["id"]
    return _ls_store_id


@router.get("/status", response_model=PlanStatus)
async def get_plan_status(user=Depends(get_current_user)):
    supabase = get_supabase_admin()
    result = (
        supabase.table("profiles")
        .select("plan, checkout_credits")
        .eq("id", user["user_id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Profile not found")
    row = result.data[0]
    return PlanStatus(plan=row["plan"], checkout_credits=row["checkout_credits"])


@router.post("/select", response_model=PlanStatus)
async def select_free_plan(req: PlanSelectRequest, user=Depends(get_current_user)):
    supabase = get_supabase_admin()
    supabase.table("profiles").update({"plan": "free"}).eq(
        "id", user["user_id"]
    ).execute()
    return PlanStatus(plan="free", checkout_credits=2)


@router.post("/checkout", response_model=PlanCheckoutResponse)
async def create_pro_checkout(user=Depends(get_current_user)):
    store_id = await _get_store_id()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.lemonsqueezy.com/v1/checkouts",
            headers={
                "Authorization": f"Bearer {settings.lemonsqueezy_api_key}",
                "Accept": "application/vnd.api+json",
                "Content-Type": "application/vnd.api+json",
            },
            json={
                "data": {
                    "type": "checkouts",
                    "attributes": {
                        "checkout_data": {
                            "custom": {"user_id": user["user_id"]},
                        },
                        "product_options": {
                            "redirect_url": f"{settings.frontend_origin}/dashboard",
                        },
                    },
                    "relationships": {
                        "store": {"data": {"type": "stores", "id": store_id}},
                        "variant": {
                            "data": {
                                "type": "variants",
                                "id": settings.lemonsqueezy_variant_id,
                            }
                        },
                    },
                }
            },
        )
    if resp.status_code != 201:
        raise HTTPException(status_code=502, detail="Failed to create LemonSqueezy checkout")
    checkout_url: str = resp.json()["data"]["attributes"]["url"]
    return PlanCheckoutResponse(checkout_url=checkout_url)
