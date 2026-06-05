"""
Unit tests for OTPRequest (and helper validators in models/user.py).
These run without any I/O — pure model validation.
"""
import pytest
from pydantic import ValidationError

from models.user import OTPRequest


VALID = {
    "email": "alice@example.com",
    "phone": "+40712345678",
    "city": "Bucharest",
    "country": "Romania",
}


class TestOTPRequestValid:
    def test_minimal_fields_accepted(self):
        req = OTPRequest(**VALID)
        assert req.email == "alice@example.com"
        assert req.phone == "+40712345678"
        assert req.city == "Bucharest"
        assert req.state is None
        assert req.country == "Romania"

    def test_state_optional_none_by_default(self):
        req = OTPRequest(**VALID)
        assert req.state is None

    def test_state_accepted_when_provided(self):
        req = OTPRequest(**{**VALID, "state": "Ilfov"})
        assert req.state == "Ilfov"

    def test_state_accepted_as_explicit_none(self):
        req = OTPRequest(**{**VALID, "state": None})
        assert req.state is None

    def test_email_normalised_to_lowercase(self):
        req = OTPRequest(**{**VALID, "email": "Alice@EXAMPLE.COM"})
        assert req.email == "alice@example.com"

    def test_various_valid_e164_phones(self):
        for phone in ("+1212555000", "+447911123456", "+33612345678"):
            req = OTPRequest(**{**VALID, "phone": phone})
            assert req.phone == phone


class TestOTPRequestInvalidEmail:
    def test_missing_at_symbol(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "email": "notanemail"})

    def test_missing_domain(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "email": "user@"})

    def test_missing_local_part(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "email": "@example.com"})

    def test_empty_string(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "email": ""})


class TestOTPRequestInvalidPhone:
    def test_missing_plus_prefix(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "phone": "40712345678"})

    def test_plus_only(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "phone": "+"})

    def test_too_short(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "phone": "+1234"})

    def test_contains_letters(self):
        with pytest.raises(ValidationError):
            OTPRequest(**{**VALID, "phone": "+4071ABC5678"})


class TestOTPRequestMissingFields:
    @pytest.mark.parametrize("field", ["email", "phone", "city", "country"])
    def test_required_field_missing(self, field):
        data = {k: v for k, v in VALID.items() if k != field}
        with pytest.raises(ValidationError):
            OTPRequest(**data)
