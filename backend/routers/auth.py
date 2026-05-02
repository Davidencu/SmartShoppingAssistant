from fastapi import APIRouter, Depends, HTTPException, Header, status
from uuid import UUID
from models.user import ProfileCreate, ProfileResponse
from services.supabase_service import SupabaseService
from core.config import get_settings, Settings

router = APIRouter(prefix="/auth", tags=["auth"])


def _extract_user_id(authorization: str = Header(...)) -> UUID:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    settings = get_settings()
    from supabase import create_client
    client = create_client(settings.supabase_url, settings.supabase_service_role_key)
    user_resp = client.auth.get_user(token)
    if not user_resp or not user_resp.user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return UUID(user_resp.user.id)


@router.post("/profile", response_model=ProfileResponse, status_code=status.HTTP_201_CREATED)
def create_profile(
    data: ProfileCreate,
    user_id: UUID = Depends(_extract_user_id),
) -> ProfileResponse:
    svc = SupabaseService()
    if svc.profile_exists(user_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists")
    return svc.create_profile(user_id, data)


@router.get("/profile/exists")
def profile_exists(user_id: UUID = Depends(_extract_user_id)) -> dict:
    svc = SupabaseService()
    return {"exists": svc.profile_exists(user_id)}
