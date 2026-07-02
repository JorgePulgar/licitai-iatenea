"""LIC-053 — security primitives: bcrypt cost 12, hash/verify round-trip."""
import pytest
from app.core.security import hash_password, verify_password


def test_hash_and_verify_round_trip():
    plain = "SuperSecret123!"
    hashed = hash_password(plain)
    assert hashed != plain
    assert verify_password(plain, hashed)


def test_verify_wrong_password_returns_false():
    hashed = hash_password("correct-horse-battery")
    assert not verify_password("wrong-password", hashed)


def test_hash_uses_bcrypt_cost_12():
    """Verify the generated hash encodes cost factor 12 (bcrypt format: $2b$12$...)."""
    hashed = hash_password("any-password")
    assert hashed.startswith("$2b$12$"), f"Expected bcrypt cost 12, got: {hashed[:10]}"
