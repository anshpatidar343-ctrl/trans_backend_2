import os
import logging
from typing import Any, Dict, Iterable, Optional

import firebase_admin
from firebase_admin import credentials, messaging

logger = logging.getLogger(__name__)
FCM_DEBUG = os.environ.get("FCM_DEBUG", "false").lower() == "true"

_APP: Optional[firebase_admin.App] = None


def _get_app() -> firebase_admin.App:
    """
    Initializes Firebase Admin SDK once per process.

    Requires env var:
      - FIREBASE_CREDENTIALS: absolute path to service-account JSON file
    """
    global _APP
    if _APP is not None:
        return _APP

    cred_path = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
    if not cred_path:
        raise RuntimeError("FIREBASE_CREDENTIALS env var is not set.")
    if not os.path.exists(cred_path):
        raise RuntimeError(f"FIREBASE_CREDENTIALS file not found at: {cred_path}")

    if FCM_DEBUG:
        logger.info("[FCM] Initializing Firebase Admin SDK...")

    cred = credentials.Certificate(cred_path)
    _APP = firebase_admin.initialize_app(cred)
    return _APP


def send_notification(
    *,
    token: str,
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    android_channel_id: str = "high_priority",
) -> str:
    """
    Send to a single device token.

    - Uses high priority on Android.
    - Includes both "notification" and "data" so background devices show a push.
    """
    _get_app()
    if FCM_DEBUG:
        # Don't log token itself; it can be used to message the device.
        logger.info(
            "[FCM] send_notification channel=%s token_len=%s title=%s data=%s",
            android_channel_id,
            len(token),
            title,
            data or {},
        )
    msg = messaging.Message(
        token=token,
        notification=messaging.Notification(title=title, body=body),
        data=(data or {}),
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(
                channel_id=android_channel_id,
            ),
        ),
    )
    try:
        return messaging.send(msg)
    except Exception:
        logger.exception(
            "[FCM] send_notification failed channel=%s title=%s data=%s",
            android_channel_id,
            title,
            data or {},
        )
        raise


def send_multicast(
    *,
    tokens: Iterable[str],
    title: str,
    body: str,
    data: Optional[Dict[str, str]] = None,
    android_channel_id: str = "high_priority",
) -> Dict[str, Any]:
    """
    Send to many tokens (best-effort).
    Returns dict with counts and per-token errors.
    """
    _get_app()
    tks = [t.strip() for t in tokens if t and str(t).strip()]
    if not tks:
        return {"success_count": 0, "failure_count": 0, "errors": []}

    if FCM_DEBUG:
        logger.info(
            "[FCM] send_multicast count=%s channel=%s title=%s data=%s",
            len(tks),
            android_channel_id,
            title,
            data or {},
        )

    msg = messaging.MulticastMessage(
        tokens=tks,
        notification=messaging.Notification(title=title, body=body),
        data=(data or {}),
        android=messaging.AndroidConfig(
            priority="high",
            notification=messaging.AndroidNotification(channel_id=android_channel_id),
        ),
    )
    try:
        # firebase-admin versions differ:
        # - some have messaging.send_multicast
        # - others only have messaging.send_each_for_multicast
        if hasattr(messaging, "send_multicast"):
            resp = messaging.send_multicast(msg)  # type: ignore[attr-defined]
        else:
            resp = messaging.send_each_for_multicast(msg)
    except Exception:
        logger.exception(
            "[FCM] send_multicast failed count=%s channel=%s title=%s data=%s",
            len(tks),
            android_channel_id,
            title,
            data or {},
        )
        raise
    errors = []
    for idx, r in enumerate(resp.responses):
        if not r.success:
            errors.append({"token": tks[idx], "error": str(r.exception)})
    return {
        "success_count": resp.success_count,
        "failure_count": resp.failure_count,
        "errors": errors,
    }


def send_data_notification(
    *,
    token: str,
    data: Optional[Dict[str, str]] = None,
    android_channel_id: str = "high_priority",
) -> str:
    """
    Send a data-only message (no `notification` payload).

    This is required so Android can deliver the message to the app's
    background handler (onBackgroundMessage) reliably.
    """
    _get_app()
    msg_type = (data or {}).get("type", "")
    if msg_type in {"booking_request", "NEW_BOOKING"}:
        # Use print() so dev server console always shows it.
        print(f"[FCM] send_data_notification {msg_type} token_len={len(token)}")
    msg = messaging.Message(
        token=token,
        data=(data or {}),
        android=messaging.AndroidConfig(priority="high"),
    )
    try:
        return messaging.send(msg)
    except Exception:
        logger.exception(
            "[FCM] send_data_notification failed channel=%s data=%s",
            android_channel_id,
            data or {},
        )
        raise


def send_data_multicast(
    *,
    tokens: Iterable[str],
    data: Optional[Dict[str, str]] = None,
    android_channel_id: str = "high_priority",
) -> Dict[str, Any]:
    """
    Send a data-only message to many tokens (no `notification` payload).

    This is required so Android can deliver the message to the app's
    background handler (onBackgroundMessage) reliably.
    """
    _get_app()
    tks = [t.strip() for t in tokens if t and str(t).strip()]
    if not tks:
        return {"success_count": 0, "failure_count": 0, "errors": []}
    msg_type = (data or {}).get("type", "")
    if msg_type in {"booking_request", "NEW_BOOKING"}:
        print(f"[FCM] send_data_multicast {msg_type} tokens={len(tks)}")

    msg = messaging.MulticastMessage(
        tokens=tks,
        data=(data or {}),
        android=messaging.AndroidConfig(priority="high"),
    )
    try:
        if hasattr(messaging, "send_multicast"):
            resp = messaging.send_multicast(msg)  # type: ignore[attr-defined]
        else:
            resp = messaging.send_each_for_multicast(msg)
    except Exception:
        logger.exception(
            "[FCM] send_data_multicast failed count=%s channel=%s data=%s",
            len(tks),
            android_channel_id,
            data or {},
        )
        raise

    errors = []
    for idx, r in enumerate(resp.responses):
        if not r.success:
            errors.append({"token": tks[idx], "error": str(r.exception)})
    return {
        "success_count": resp.success_count,
        "failure_count": resp.failure_count,
        "errors": errors,
    }

