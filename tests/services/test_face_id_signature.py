from app.services.face_id.signature import build_face_id_signature, verify_face_id_signature


def test_face_id_signature_roundtrip():
    secret = "test-secret"
    ts = "1711111111"
    body = b'{"asset_id":"abc","status":"ready"}'
    sig = build_face_id_signature(secret, ts, body)
    assert verify_face_id_signature(secret, ts, body, sig) is True


def test_face_id_signature_rejects_modified_body():
    secret = "test-secret"
    ts = "1711111111"
    body = b'{"asset_id":"abc","status":"ready"}'
    sig = build_face_id_signature(secret, ts, body)
    assert verify_face_id_signature(secret, ts, b'{"asset_id":"abc","status":"failed"}', sig) is False
