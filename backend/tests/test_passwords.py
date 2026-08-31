import pytest

from app.security.passwords import (
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password,
    verify_password,
)


def test_hash_is_argon2id_and_verifies():
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple") is True


def test_verify_returns_false_on_mismatch_without_raising():
    h = hash_password("the-right-password")
    assert verify_password(h, "the-wrong-password") is False


def test_verify_false_on_corrupt_hash():
    assert verify_password("not-a-real-hash", "whatever") is False


def test_needs_rehash_false_for_fresh_true_for_weak():
    from argon2 import PasswordHasher

    fresh = hash_password("a-strong-enough-password")
    assert needs_rehash(fresh) is False
    weak = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash("x" * 12)
    assert needs_rehash(weak) is True


def test_password_policy():
    validate_password("x" * 12)  # ok
    with pytest.raises(PasswordPolicyError):
        validate_password("short")
    with pytest.raises(PasswordPolicyError):
        validate_password("x" * 200)
