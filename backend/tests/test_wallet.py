import hashlib
import hmac
import json
import pytest
from unittest.mock import MagicMock
from uuid import uuid4

from models.wallet import Wallet, WalletTransaction, TransactionType
from services.supabase_service import SupabaseService
from routers.webhooks import _verify_lemonsqueezy_signature
from tests.conftest import (
    TEST_USER_ID,
    TEST_WALLET_ID,
    NOW,
    _make_wallet_row,
    _make_txn_row,
)


# ── Wallet model ──────────────────────────────────────────────────────────────

class TestWalletModel:
    def test_available_cents_is_balance_minus_frozen(self):
        wallet = Wallet(
            id=uuid4(),
            user_id=TEST_USER_ID,
            balance_cents=10000,
            frozen_cents=3000,
            currency="USD",
            updated_at=NOW,
        )
        assert wallet.available_cents == 7000

    def test_available_cents_zero_when_fully_frozen(self):
        wallet = Wallet(
            id=uuid4(),
            user_id=TEST_USER_ID,
            balance_cents=5000,
            frozen_cents=5000,
            currency="USD",
            updated_at=NOW,
        )
        assert wallet.available_cents == 0

    def test_transaction_type_enum_values(self):
        assert TransactionType.TOPUP == "TOPUP"
        assert TransactionType.FREEZE == "FREEZE"
        assert TransactionType.DEDUCT == "DEDUCT"
        assert TransactionType.REFUND == "REFUND"


# ── SupabaseService.get_wallet ────────────────────────────────────────────────

class TestSupabaseServiceGetWallet:
    def _svc(self, db: MagicMock) -> SupabaseService:
        return SupabaseService(client=db)

    def test_returns_wallet_with_transactions(self):
        db = MagicMock()

        wallet_chain = db.table.return_value.select.return_value.eq.return_value.single.return_value.execute
        wallet_chain.return_value.data = _make_wallet_row(TEST_USER_ID, balance=10000)

        txn_chain = (
            db.table.return_value
            .select.return_value
            .eq.return_value
            .order.return_value
            .limit.return_value
            .execute
        )
        txn_chain.return_value.data = [
            _make_txn_row(TEST_WALLET_ID, "TOPUP", 10000)
        ]

        def table_side(name):
            m = MagicMock()
            if name == "wallets":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
                    _make_wallet_row(TEST_USER_ID, balance=10000)
                )
            else:
                m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = [
                    _make_txn_row(TEST_WALLET_ID, "TOPUP", 10000)
                ]
            return m

        db.table.side_effect = table_side
        svc = self._svc(db)
        result = svc.get_wallet(TEST_USER_ID)

        assert result.wallet.balance_cents == 10000
        assert len(result.recent_transactions) == 1
        assert result.recent_transactions[0].type == TransactionType.TOPUP

    def test_empty_transaction_history(self):
        db = MagicMock()

        def table_side(name):
            m = MagicMock()
            if name == "wallets":
                m.select.return_value.eq.return_value.single.return_value.execute.return_value.data = (
                    _make_wallet_row(TEST_USER_ID)
                )
            else:
                m.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
            return m

        db.table.side_effect = table_side
        svc = self._svc(db)
        result = svc.get_wallet(TEST_USER_ID)

        assert result.wallet.balance_cents == 0
        assert result.recent_transactions == []


# ── SupabaseService.credit_wallet ─────────────────────────────────────────────

class TestSupabaseServiceCreditWallet:
    def test_calls_rpc_credit_wallet(self):
        db = MagicMock()
        db.rpc.return_value.execute.return_value.data = [
            _make_txn_row(TEST_WALLET_ID, "TOPUP", 5000)
        ]
        svc = SupabaseService(client=db)
        txn = svc.credit_wallet(TEST_USER_ID, 5000, "ls_order_abc")

        db.rpc.assert_called_once_with(
            "credit_wallet",
            {
                "p_user_id": str(TEST_USER_ID),
                "p_amount_cents": 5000,
                "p_reference_id": "ls_order_abc",
            },
        )
        assert txn.amount_cents == 5000
        assert txn.type == TransactionType.TOPUP


# ── LemonSqueezy webhook signature verification ───────────────────────────────

class TestLemonSqueezyWebhookSignature:
    SECRET = "super-secret"

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self.SECRET.encode(), payload, hashlib.sha256).hexdigest()

    def test_valid_signature_returns_true(self):
        payload = b'{"meta":{"event_name":"order_created"}}'
        sig = self._sign(payload)
        assert _verify_lemonsqueezy_signature(payload, sig, self.SECRET) is True

    def test_wrong_signature_returns_false(self):
        payload = b'{"meta":{"event_name":"order_created"}}'
        assert _verify_lemonsqueezy_signature(payload, "bad_sig", self.SECRET) is False

    def test_tampered_payload_fails(self):
        original = b'{"meta":{"event_name":"order_created"}}'
        sig = self._sign(original)
        tampered = b'{"meta":{"event_name":"order_created"},"extra":"injected"}'
        assert _verify_lemonsqueezy_signature(tampered, sig, self.SECRET) is False

    def test_empty_secret_does_not_match_non_empty(self):
        payload = b'test'
        sig = self._sign(payload)
        assert _verify_lemonsqueezy_signature(payload, sig, "wrong-secret") is False
