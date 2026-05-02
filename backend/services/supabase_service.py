from supabase import create_client, Client
from uuid import UUID
from core.config import get_settings
from models.user import ProfileCreate, UserProfile, UserAddress, ProfileResponse
from models.wallet import Wallet, WalletTransaction, WalletResponse, TransactionType


def _make_client() -> Client:
    s = get_settings()
    return create_client(s.supabase_url, s.supabase_service_role_key)


class SupabaseService:
    def __init__(self, client: Client | None = None) -> None:
        self._db = client or _make_client()

    # ── Auth / Profile ────────────────────────────────────────────────────────

    def create_profile(self, user_id: UUID, data: ProfileCreate) -> ProfileResponse:
        profile_row = (
            self._db.table("profiles")
            .insert({"id": str(user_id), "full_name": data.full_name, "phone": data.phone})
            .execute()
        )
        address_row = (
            self._db.table("addresses")
            .insert(
                {
                    "user_id": str(user_id),
                    "recipient_name": data.address.recipient_name,
                    "street": data.address.street,
                    "city": data.address.city,
                    "state": data.address.state,
                    "country": data.address.country,
                    "zip_code": data.address.zip_code,
                    "is_default": True,
                }
            )
            .execute()
        )
        return ProfileResponse(
            profile=UserProfile(**profile_row.data[0]),
            address=UserAddress(**address_row.data[0]),
        )

    def profile_exists(self, user_id: UUID) -> bool:
        row = (
            self._db.table("profiles")
            .select("id")
            .eq("id", str(user_id))
            .maybe_single()
            .execute()
        )
        return row.data is not None

    # ── Wallet ────────────────────────────────────────────────────────────────

    def get_wallet(self, user_id: UUID) -> WalletResponse:
        wallet_row = (
            self._db.table("wallets")
            .select("*")
            .eq("user_id", str(user_id))
            .single()
            .execute()
        )
        txn_rows = (
            self._db.table("wallet_transactions")
            .select("*")
            .eq("wallet_id", wallet_row.data["id"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
        )
        wallet = Wallet(**wallet_row.data)
        transactions = [WalletTransaction(**r) for r in txn_rows.data]
        return WalletResponse(wallet=wallet, recent_transactions=transactions)

    def credit_wallet(
        self, user_id: UUID, amount_cents: int, reference_id: str
    ) -> WalletTransaction:
        result = self._db.rpc(
            "credit_wallet",
            {
                "p_user_id": str(user_id),
                "p_amount_cents": amount_cents,
                "p_reference_id": reference_id,
            },
        ).execute()
        return WalletTransaction(**result.data[0])
