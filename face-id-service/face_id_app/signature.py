import hashlib
import hmac


def build_signature(secret: str, timestamp: str, body: bytes) -> str:
    signed = timestamp.encode("utf-8") + body
    return hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
