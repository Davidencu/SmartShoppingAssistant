from fastapi import APIRouter, Depends, HTTPException, status
from uuid import UUID
from models.wallet import WalletResponse
from services.supabase_service import SupabaseService
from routers.auth import _extract_user_id

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("", response_model=WalletResponse)
def get_wallet(user_id: UUID = Depends(_extract_user_id)) -> WalletResponse:
    try:
        return SupabaseService().get_wallet(user_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
