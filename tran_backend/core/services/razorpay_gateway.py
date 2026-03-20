import os
import hmac
import hashlib
from typing import Any, Dict

import razorpay


def _key_id() -> str:
    return (os.environ.get("RAZORPAY_KEY_ID") or "").strip()


def _key_secret() -> str:
    return (os.environ.get("RAZORPAY_KEY_SECRET") or "").strip()


def get_client() -> razorpay.Client:
    key_id = _key_id()
    key_secret = _key_secret()
    if not key_id or not key_secret:
        raise RuntimeError("RAZORPAY_KEY_ID/RAZORPAY_KEY_SECRET env vars are not set.")
    return razorpay.Client(auth=(key_id, key_secret))


def create_order(*, amount_paise: int, receipt: str, notes: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """
    Create Razorpay order (amount in paise).
    """
    client = get_client()
    return client.order.create(
        {
            "amount": int(amount_paise),
            "currency": "INR",
            "receipt": receipt,
            "payment_capture": 1,
            "notes": notes or {},
        }
    )


def verify_signature(*, order_id: str, payment_id: str, signature: str) -> bool:
    """
    Verify Razorpay signature (HMAC SHA256 of order_id|payment_id with key_secret).
    """
    secret = _key_secret().encode("utf-8")
    body = f"{order_id}|{payment_id}".encode("utf-8")
    expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, (signature or "").strip())

