import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict

from django.conf import settings


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    # Pad to a multiple of 4 for urlsafe base64 decoding.
    padding = "=" * ((4 - (len(s) % 4)) % 4)
    return base64.urlsafe_b64decode((s + padding).encode("ascii"))


def create_driver_access_token(*, driver_id: int, expires_in_seconds: int = 7 * 24 * 3600) -> str:
    """
    Minimal JWT-like implementation (HS256) to avoid extra dependencies.
    Payload includes:
      - sub: driver_id
      - role: 'driver'
      - type: 'access'
      - iat/exp
    """
    header = {"alg": "HS256", "typ": "JWT"}
    now = int(time.time())
    payload: Dict[str, Any] = {
        "sub": str(driver_id),
        "role": "driver",
        "type": "access",
        "iat": now,
        "exp": now + int(expires_in_seconds),
    }

    header_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    key = settings.SECRET_KEY.encode("utf-8")
    signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    signature_b64 = _b64url_encode(signature)
    return f"{header_b64}.{payload_b64}.{signature_b64}"


def decode_driver_access_token(token: str) -> Dict[str, Any]:
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format.")

    header_b64, payload_b64, signature_b64 = parts
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    key = settings.SECRET_KEY.encode("utf-8")
    expected_signature = hmac.new(key, signing_input, hashlib.sha256).digest()
    expected_b64 = _b64url_encode(expected_signature)

    # Constant-time compare to prevent timing attacks.
    if not hmac.compare_digest(expected_b64, signature_b64):
        raise ValueError("Invalid token signature.")

    payload_raw = _b64url_decode(payload_b64)
    payload = json.loads(payload_raw.decode("utf-8"))

    if payload.get("role") != "driver":
        raise ValueError("Invalid role.")
    if payload.get("type") != "access":
        raise ValueError("Invalid token type.")

    exp = payload.get("exp")
    if exp is None:
        raise ValueError("Token missing exp.")
    if int(time.time()) >= int(exp):
        raise ValueError("Token expired.")

    return payload

