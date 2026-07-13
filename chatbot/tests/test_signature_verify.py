"""X-Hub-Signature-256 verification."""

import hashlib
import hmac

from app.channel.signature_verify import verify_signature

SECRET = "app-secret"


def _sig(body: bytes) -> str:
    return "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature():
    body = b'{"object":"page"}'
    assert verify_signature(body, _sig(body), SECRET) is True


def test_tampered_body_rejected():
    header = _sig(b'{"a":1}')
    assert verify_signature(b'{"a":2}', header, SECRET) is False


def test_missing_header_rejected():
    assert verify_signature(b"x", None, SECRET) is False


def test_malformed_header_rejected():
    assert verify_signature(b"x", "md5=deadbeef", SECRET) is False


def test_wrong_secret_rejected():
    body = b"hello"
    assert verify_signature(body, _sig(body), "other-secret") is False
