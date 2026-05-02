import pytest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pydantic import ValidationError

from models.user import ProfileCreate, Address
from services.supabase_service import SupabaseService
from tests.conftest import (
    TEST_USER_ID,
    _make_profile_row,
    _make_address_row,
)


# ── ProfileCreate validation ──────────────────────────────────────────────────

class TestProfileCreateValidation:
    def test_valid_profile(self):
        profile = ProfileCreate(
            full_name="Ion Popescu",
            phone="+40712345678",
            address=Address(
                recipient_name="Ion Popescu",
                street="Strada Victoriei 1",
                city="București",
                country="RO",
                zip_code="010011",
            ),
        )
        assert profile.phone == "+40712345678"
        assert profile.full_name == "Ion Popescu"

    def test_phone_strips_spaces_and_dashes(self):
        profile = ProfileCreate(
            full_name="Test User",
            phone="+40 712 345 678",
            address=Address(
                recipient_name="Test User",
                street="Str Test 1",
                city="Cluj",
                country="RO",
                zip_code="400001",
            ),
        )
        assert " " not in profile.phone

    def test_invalid_phone_raises(self):
        with pytest.raises(ValidationError) as exc_info:
            ProfileCreate(
                full_name="Ion",
                phone="abc",
                address=Address(
                    recipient_name="Ion",
                    street="Str Test 1",
                    city="Cluj",
                    country="RO",
                    zip_code="400001",
                ),
            )
        assert "Invalid phone number" in str(exc_info.value)

    def test_full_name_too_short_raises(self):
        with pytest.raises(ValidationError):
            ProfileCreate(
                full_name="X",
                phone="+40712345678",
                address=Address(
                    recipient_name="X",
                    street="Str Test 1",
                    city="Cluj",
                    country="RO",
                    zip_code="400001",
                ),
            )

    def test_empty_street_raises(self):
        with pytest.raises(ValidationError):
            Address(
                recipient_name="Ion",
                street="Ab",  # too short
                city="Cluj",
                country="RO",
                zip_code="400001",
            )

    def test_state_is_optional(self):
        addr = Address(
            recipient_name="Ion",
            street="Strada Unirii 10",
            city="Cluj",
            country="RO",
            zip_code="400001",
        )
        assert addr.state is None


# ── SupabaseService.create_profile ────────────────────────────────────────────

class TestSupabaseServiceCreateProfile:
    def _svc(self, mock_db: MagicMock) -> SupabaseService:
        return SupabaseService(client=mock_db)

    def _valid_data(self) -> ProfileCreate:
        return ProfileCreate(
            full_name="Ion Popescu",
            phone="+40712345678",
            address=Address(
                recipient_name="Ion Popescu",
                street="Strada Victoriei 1",
                city="București",
                country="RO",
                zip_code="010011",
            ),
        )

    def test_create_profile_calls_correct_tables(self):
        db = MagicMock()
        db.table.return_value.insert.return_value.execute.return_value.data = [
            _make_profile_row(TEST_USER_ID)
        ]

        # second call is for addresses table
        call_count = [0]
        def table_side_effect(name):
            call_count[0] += 1
            m = MagicMock()
            if name == "profiles":
                m.insert.return_value.execute.return_value.data = [_make_profile_row(TEST_USER_ID)]
            else:
                m.insert.return_value.execute.return_value.data = [_make_address_row(TEST_USER_ID)]
            return m

        db.table.side_effect = table_side_effect
        svc = self._svc(db)
        result = svc.create_profile(TEST_USER_ID, self._valid_data())

        assert result.profile.full_name == "Ion Popescu"
        assert result.address.city == "București"
        assert call_count[0] == 2  # profiles + addresses

    def test_profile_exists_returns_true_when_found(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
            "id": str(TEST_USER_ID)
        }
        svc = self._svc(db)
        assert svc.profile_exists(TEST_USER_ID) is True

    def test_profile_exists_returns_false_when_not_found(self):
        db = MagicMock()
        db.table.return_value.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
        svc = self._svc(db)
        assert svc.profile_exists(TEST_USER_ID) is False
