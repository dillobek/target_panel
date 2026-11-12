import base64

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import ENCRYPTION_KEY


def decrypt(value: str) -> str:
    """NestJS crypto.util.ts formati: base64(iv[12] | ciphertext | tag[16])."""
    key = base64.b64decode(ENCRYPTION_KEY)
    raw = base64.b64decode(value)
    return AESGCM(key).decrypt(raw[:12], raw[12:], None).decode()


def encrypt(plain: str) -> str:
    import os

    key = base64.b64decode(ENCRYPTION_KEY)
    iv = os.urandom(12)
    return base64.b64encode(iv + AESGCM(key).encrypt(iv, plain.encode(), None)).decode()
