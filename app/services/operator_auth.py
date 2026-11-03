"""Single-operator password verification; no plaintext password storage."""

import hashlib
import hmac

from app.config import settings
from app.services.passwords import verify_password


def auth_configured() -> bool:
    return bool(settings.operator_username and settings.operator_password_hash.get_secret_value())


def verify_operator(username: str, password: str) -> bool:
    valid_username = hmac.compare_digest(username.encode(), settings.operator_username.encode())
    valid_password = verify_password(password, settings.operator_password_hash.get_secret_value())
    return auth_configured() and valid_username and valid_password


def credential_version() -> str:
    value = settings.operator_username + ":" + settings.operator_password_hash.get_secret_value()
    return hashlib.sha256(value.encode()).hexdigest()
