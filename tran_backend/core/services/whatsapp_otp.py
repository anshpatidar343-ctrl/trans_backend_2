import hashlib
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from typing import Any, Dict, Optional, Tuple

import requests
from django.core.cache import cache


HYPER_URL_BASE = "https://app.hypersender.com/api/whatsapp/v2"


def _api_key() -> str:
    # Defaults are for local dev convenience; in production set env vars.
    return (os.environ.get("HYPERsender_API_KEY") or "1119|HK5rlDllCrK9x0UqdZTRtBcMLtjg14z43q0YZ8A8ae7047f0").strip()


def _instance_id() -> str:
    # Defaults are for local dev convenience; in production set env vars.
    return (os.environ.get("HYPERsender_INSTANCE_ID") or "a11fec5f-d083-43ee-af5e-b5dda6e3a6d5").strip()


def _otp_salt() -> str:
    return (os.environ.get("WA_OTP_SALT") or "default-wa-otp-salt").strip()


def _normalize_phone(phone: str) -> str:
    """
    WhatsApp chatId typically requires country code, e.g. 91XXXXXXXXXX@c.us
    If your DB stores 10-digit local numbers, auto-prefix by default.
    """
    digits = "".join(ch for ch in str(phone) if ch.isdigit())
    if not digits:
        return ""

    # Normalize numbers like 00<country><number> -> <country><number>
    if digits.startswith("00") and len(digits) > 2:
        digits = digits[2:]

    default_cc = (os.environ.get("WA_DEFAULT_COUNTRY_CODE") or "91").strip()
    if default_cc and len(digits) == 10 and not digits.startswith(default_cc):
        digits = f"{default_cc}{digits}"

    return digits


def _otp_hash(otp: str) -> str:
    salt = _otp_salt()
    return hashlib.sha256(f"{otp}{salt}".encode("utf-8")).hexdigest()


OTP_TTL_SECONDS = 300  # 5 minutes
MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class OtpSendResult:
    otp_token: str
    phone_masked: str
    expires_in_seconds: int
    queued_request_uuid: Optional[str] = None
    queued_request_link: Optional[str] = None


def _mask_phone(phone: str) -> str:
    digits = _normalize_phone(phone)
    if len(digits) <= 4:
        return digits
    return f"{'*' * (len(digits) - 4)}{digits[-4:]}"


def send_whatsapp_otp(*, phone: str, purpose: str, otp: Optional[str] = None) -> OtpSendResult:
    """
    Send OTP via HyperSender WhatsApp and store OTP hash in Django cache.
    Returns an `otp_token` that the client must send back for verification.
    """
    api_key = _api_key()
    instance_id = _instance_id()
    if not api_key or not instance_id:
        raise RuntimeError("HYPERsender_API_KEY / HYPERsender_INSTANCE_ID env vars are not set.")

    digits = _normalize_phone(phone)
    if not digits:
        raise ValueError("Invalid phone number.")

    # Generate 6-digit OTP.
    otp_value = otp or f"{secrets.randbelow(1000000):06d}"
    otp_token = str(uuid.uuid4())

    cache_key = f"wa_otp:{otp_token}"
    cache.set(
        cache_key,
        {
            "phone": digits,
            "purpose": purpose,
            "otp_hash": _otp_hash(otp_value),
            "attempts": 0,
            "created_at": datetime.now(dt_timezone.utc).isoformat(),
        },
        timeout=OTP_TTL_SECONDS,
    )

    chat_id = f"{digits}@c.us"
    message = f"Your OTP for E-Transport {purpose.replace('_', ' ')} is: {otp_value}. It expires in 5 minutes."

    url = f"{HYPER_URL_BASE}/{instance_id}/send-text-safe"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    body = {
        "chatId": chat_id,
        "text": message,
        "linkPreview": False,
        "linkPreviewHighQuality": False,
    }

    queued_request_uuid: Optional[str] = None
    queued_request_link: Optional[str] = None
    # queued response is OK; if send fails, raise.
    resp = requests.post(url, headers=headers, json=body, timeout=20)
    resp.raise_for_status()

    try:
        data = resp.json()
        queued_request_uuid = (data.get("queued_request_uuid") or "").strip() or None
        queued_request_link = (data.get("queued_request_link") or "").strip() or None
    except Exception:
        # Non-JSON response; ignore.
        pass

    # Don’t log OTP (security).
    return OtpSendResult(
        otp_token=otp_token,
        phone_masked=_mask_phone(digits),
        expires_in_seconds=OTP_TTL_SECONDS,
        queued_request_uuid=queued_request_uuid,
        queued_request_link=queued_request_link,
    )


def verify_whatsapp_otp(
    *,
    otp_token: str,
    otp: str,
    purpose: str,
    phone: Optional[str] = None,
) -> Tuple[bool, str]:
    """
    Verify OTP for a given `purpose` using otp_token.
    Returns (verified, message).
    """
    if not otp_token:
        return False, "otp_token is required."
    if not otp:
        return False, "otp is required."

    cache_key = f"wa_otp:{otp_token}"
    data: Optional[Dict[str, Any]] = cache.get(cache_key)
    if not data:
        return False, "OTP expired or invalid."
    if data.get("purpose") != purpose:
        return False, "OTP purpose mismatch."
    if phone is not None:
        if data.get("phone") != _normalize_phone(phone):
            return False, "OTP phone mismatch."

    expected = data.get("otp_hash")
    if not expected:
        cache.delete(cache_key)
        return False, "OTP invalid."

    if _otp_hash(str(otp).strip()) == expected:
        cache.delete(cache_key)
        return True, "OTP verified."

    # wrong otp
    attempts = int(data.get("attempts") or 0) + 1
    if attempts >= MAX_ATTEMPTS:
        cache.delete(cache_key)
        return False, "Too many attempts. OTP expired."

    cache.set(cache_key, {**data, "attempts": attempts}, timeout=OTP_TTL_SECONDS)
    return False, "Invalid OTP."

