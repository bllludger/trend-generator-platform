import hashlib
import hmac


def build_face_id_signature(secret: str, timestamp: str, body: bytes) -> str:
    payload = (timestamp.encode("utf-8") + body)
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def verify_face_id_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    expected = build_face_id_signature(secret, timestamp, body)
    return hmac.compare_digest(expected, signature or "")

