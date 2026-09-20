from cryptography.fernet import Fernet, InvalidToken


class Cipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except Exception as exc:
            raise RuntimeError("CALLIOPE_ENCRYPTION_KEY must be a valid Fernet key") from exc

    def encrypt(self, value: str) -> bytes:
        return self._fernet.encrypt(value.encode("utf-8"))

    def decrypt(self, value: bytes) -> str:
        try:
            return self._fernet.decrypt(value).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt stored Calliope data with the configured key") from exc
