import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class Cipher:
    def __init__(self, key: str) -> None:
        try:
            encoded_key = key.encode("utf-8")
            self._fernet = Fernet(encoded_key)
            raw_key = base64.urlsafe_b64decode(encoded_key)
        except Exception as exc:
            raise RuntimeError("CALLIOPE_ENCRYPTION_KEY must be a valid Fernet key") from exc
        self._index_key = hashlib.sha256(b"iris-calliope-character-index-v1" + raw_key).digest()

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt stored Calliope data with the configured key") from exc

    def fingerprint(self, value: str) -> str:
        return hmac.new(self._index_key, value.encode("utf-8"), hashlib.sha256).hexdigest()
