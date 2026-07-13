"""X-Hub-Signature-256 verification (pure, constant-time). Reject unsigned."""

import hashlib
import hmac


def verify_signature(body: bytes, header: str | None, app_secret: str) -> bool:
    """True iff `header` == 'sha256=' + HMAC-SHA256(body, app_secret).

    Missing/malformed header → False. Constant-time compare (no timing oracle).
    """
    if not header or not header.startswith("sha256="):
        return False
    provided = header.split("=", 1)[1].strip()
    expected = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)
