import os
import logging

from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.services.fcm import send_multicast, send_notification
from customers.models import Customer
from drivers.models import Driver

logger = logging.getLogger(__name__)
FCM_DEBUG = os.environ.get("FCM_DEBUG", "false").lower() == "true"


@api_view(["POST"])
def send_push(request):
    """
    POST /api/admin/push/send/

    Body:
      - title (string)
      - message (string)
      - target (string):
          "all" | "drivers" | "customers" | "user"
      - user_type (string, required when target="user"):
          "driver" | "customer"
      - user_id (int, required when target="user")
      - type (string, optional): "general_notification" (default)
      - data (object, optional): extra key/values (strings)
    """
    title = str(request.data.get("title") or "").strip()
    message = str(request.data.get("message") or "").strip()
    target = str(request.data.get("target") or "").strip().lower()
    notif_type = str(request.data.get("type") or "general_notification").strip()

    if FCM_DEBUG:
        logger.info("[FCM] admin send_push target=%s notif_type=%s title=%s", target, notif_type, title)

    if not title or not message:
        return Response({"detail": "title and message are required."}, status=status.HTTP_400_BAD_REQUEST)
    if target not in {"all", "drivers", "customers", "user"}:
        return Response({"detail": "target must be one of: all, drivers, customers, user."}, status=status.HTTP_400_BAD_REQUEST)

    extra = request.data.get("data") or {}
    data = {"type": notif_type, **{str(k): str(v) for k, v in dict(extra).items()}}

    if target == "user":
        user_type = str(request.data.get("user_type") or "").strip().lower()
        user_id = request.data.get("user_id")
        if user_type not in {"driver", "customer"} or not user_id:
            return Response({"detail": "user_type (driver|customer) and user_id are required for target=user."}, status=status.HTTP_400_BAD_REQUEST)
        if user_type == "driver":
            obj = Driver.objects.filter(pk=int(user_id)).first()
        else:
            obj = Customer.objects.filter(pk=int(user_id)).first()
        if obj is None:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        token = (getattr(obj, "fcm_token", "") or "").strip()
        if FCM_DEBUG:
            logger.info(
                "[FCM] admin push user token lookup user_type=%s user_id=%s token_len=%s",
                user_type,
                user_id,
                len(token),
            )
        if not token:
            return Response({"detail": "User has no fcm_token."}, status=status.HTTP_400_BAD_REQUEST)
        msg_id = send_notification(token=token, title=title, body=message, data=data, android_channel_id="general")
        return Response({"detail": "Sent.", "message_id": msg_id}, status=status.HTTP_200_OK)

    if target == "drivers":
        tokens = list(Driver.objects.exclude(fcm_token="").values_list("fcm_token", flat=True))
    elif target == "customers":
        tokens = list(Customer.objects.exclude(fcm_token="").values_list("fcm_token", flat=True))
    else:
        tokens = list(Driver.objects.exclude(fcm_token="").values_list("fcm_token", flat=True)) + list(
            Customer.objects.exclude(fcm_token="").values_list("fcm_token", flat=True)
        )

    if FCM_DEBUG:
        logger.info("[FCM] admin push bulk token_count=%s", len(tokens))
    result = send_multicast(tokens=tokens, title=title, body=message, data=data, android_channel_id="general")
    return Response({"detail": "Sent.", "result": result}, status=status.HTTP_200_OK)

