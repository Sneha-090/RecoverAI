import pytest

from app.services.passwords import hash_password, verify_password


def test_password_hashes_are_salted_and_verify_correctly():
    password = "test-password-123"
    first, second = hash_password(password), hash_password(password)
    assert first != second
    assert password not in first
    assert verify_password(password, first)
    assert not verify_password("another-password", first)


@pytest.mark.parametrize("encoded", ["", "bad", "pbkdf2_sha256$1$salt$digest", "pbkdf2_sha256$999999999$salt$digest"])
def test_invalid_stored_hash_fails_closed(encoded):
    assert not verify_password("test-password-123", encoded)


@pytest.mark.parametrize("password", ["short", "x" * 1025])
def test_password_length_is_bounded(password):
    with pytest.raises(ValueError):
        hash_password(password)
