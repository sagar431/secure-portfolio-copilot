import secrets

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError


class PasswordService:
    """Argon2id password hashing with a dummy verify path for unknown users."""

    def __init__(self) -> None:
        self._password_hash = PasswordHash.recommended()
        self._dummy_hash = self._password_hash.hash(secrets.token_urlsafe(32))

    def hash(self, password: str) -> str:
        return self._password_hash.hash(password)

    def verify(self, password: str, password_hash: str) -> bool:
        try:
            return self._password_hash.verify(password, password_hash)
        except (TypeError, UnknownHashError, ValueError):
            return False

    def verify_unknown_user(self, password: str) -> None:
        self.verify(password, self._dummy_hash)


password_service = PasswordService()
