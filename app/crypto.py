import base64
import hashlib
from cryptography.fernet import Fernet
from flask import current_app


def _get_fernet() -> Fernet:
    key_material = current_app.config["SECRET_KEY"].encode()
    digest = hashlib.sha256(key_material).digest()
    key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except Exception:
        return ""
