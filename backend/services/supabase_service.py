from supabase import create_client, Client

from core.config import settings


def get_supabase_admin() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)
