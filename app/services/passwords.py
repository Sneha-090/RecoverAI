"""Password hashing without database settings or provider credentials."""

import hashlib
import hmac
import secrets


ITERATIONS = 600_000


def hash_password(password: str) -> str:
    if not 12 <= len(password) <= 1024:
        raise ValueError("Use a password with 12 to 1024 characters")
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    if not 12 <= len(password) <= 1024:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        iterations = int(iterations)
        if algorithm != "pbkdf2_sha256" or not 600_000 <= iterations <= 1_000_000:
            return False
        if len(salt) != 32 or len(expected) != 64:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), iterations)
        return hmac.compare_digest(digest, bytes.fromhex(expected))
    except (ValueError, TypeError):
        return False
