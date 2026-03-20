import os
import logging

from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import Customer
from .serializers import CustomerSignupSerializer, CustomerLoginSerializer
from core.services.whatsapp_otp import OtpSendResult, send_whatsapp_otp, verify_whatsapp_otp
from django.contrib.auth.hashers import make_password

logger = logging.getLogger(__name__)
FCM_DEBUG = os.environ.get("FCM_DEBUG", "false").lower() == "true"


@api_view(["POST"])
def customer_signup(request):
    serializer = CustomerSignupSerializer(data=request.data)
    if serializer.is_valid():
        customer = serializer.save()
        return Response(
            {
                "id": customer.id,
                "full_name": customer.full_name,
                "email": customer.email,
                "phone_number": customer.phone_number,
            },
            status=status.HTTP_201_CREATED,
        )
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
def customer_login(request):
    serializer = CustomerLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    email = serializer.validated_data["email"]
    password = serializer.validated_data["password"]

    try:
        customer = Customer.objects.get(email=email)
    except Customer.DoesNotExist:
        return Response(
            {"detail": "Invalid email or password."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not check_password(password, customer.password):
        return Response(
            {"detail": "Invalid email or password."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "id": customer.id,
            "full_name": customer.full_name,
            "email": customer.email,
            "phone_number": customer.phone_number,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def customer_send_whatsapp_otp(request):
    """
    POST /api/customers/send-whatsapp-otp/
    Body: phone_number, purpose (signup|forgot_password)
    """
    phone_number = str(request.data.get("phone_number") or "").strip()
    purpose = str(request.data.get("purpose") or "").strip()
    if not phone_number:
        return Response({"detail": "phone_number is required."}, status=status.HTTP_400_BAD_REQUEST)
    if purpose not in ["signup", "forgot_password"]:
        return Response({"detail": "Invalid purpose."}, status=status.HTTP_400_BAD_REQUEST)

    if purpose == "signup":
        digits = "".join(ch for ch in phone_number if ch.isdigit())
        variants = set()
        if digits:
            variants.add(digits)
        if digits.startswith("91") and len(digits) > 2:
            variants.add(digits[2:])
        if len(digits) > 10:
            variants.add(digits[-10:])

        if Customer.objects.filter(phone_number__in=list(variants)).exists():
            return Response(
                {"detail": "Customer already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    try:
        result: OtpSendResult = send_whatsapp_otp(phone=phone_number, purpose=purpose)
    except Exception as e:
        return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    return Response(
        {
            "otp_token": result.otp_token,
            "phone_masked": result.phone_masked,
            "expires_in_seconds": result.expires_in_seconds,
            "queued_request_uuid": result.queued_request_uuid,
            "queued_request_link": result.queued_request_link,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def customer_verify_whatsapp_otp(request):
    """
    POST /api/customers/verify-whatsapp-otp/
    Body: phone_number, purpose, otp_token, otp
    """
    phone_number = str(request.data.get("phone_number") or "").strip()
    purpose = str(request.data.get("purpose") or "").strip()
    otp_token = str(request.data.get("otp_token") or "").strip()
    otp = str(request.data.get("otp") or "").strip()

    if not phone_number or not otp_token or not otp:
        return Response({"detail": "phone_number, otp_token and otp are required."}, status=status.HTTP_400_BAD_REQUEST)
    if purpose not in ["signup", "forgot_password"]:
        return Response({"detail": "Invalid purpose."}, status=status.HTTP_400_BAD_REQUEST)

    ok, msg = verify_whatsapp_otp(
        otp_token=otp_token,
        otp=otp,
        purpose=purpose,
        phone=phone_number,
    )
    if not ok:
        return Response({"verified": False, "detail": msg}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"verified": True}, status=status.HTTP_200_OK)


@api_view(["POST"])
def customer_reset_password_with_whatsapp_otp(request):
    """
    POST /api/customers/reset-password-with-whatsapp-otp/
    Body: phone_number, otp_token, otp, new_password
    """
    phone_number = str(request.data.get("phone_number") or "").strip()
    otp_token = str(request.data.get("otp_token") or "").strip()
    otp = str(request.data.get("otp") or "").strip()
    new_password = str(request.data.get("new_password") or "").strip()
    purpose = str(request.data.get("purpose") or "forgot_password").strip()

    if purpose not in ["forgot_password"]:
        return Response({"detail": "Invalid purpose."}, status=status.HTTP_400_BAD_REQUEST)
    if not phone_number or not otp_token or not otp or not new_password:
        return Response({"detail": "phone_number, otp_token, otp and new_password are required."}, status=status.HTTP_400_BAD_REQUEST)

    ok, msg = verify_whatsapp_otp(
        otp_token=otp_token,
        otp=otp,
        purpose=purpose,
        phone=phone_number,
    )
    if not ok:
        return Response({"verified": False, "detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    try:
        customer = Customer.objects.get(phone_number=phone_number)
    except Customer.DoesNotExist:
        return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

    customer.password = make_password(new_password)
    customer.save(update_fields=["password", "updated_at"])
    return Response({"detail": "Password reset successfully."}, status=status.HTTP_200_OK)


@api_view(["GET"])
def customer_status(request, customer_id: int):
    try:
        customer = Customer.objects.get(pk=customer_id)
    except Customer.DoesNotExist:
        return Response(
            {"detail": "Customer not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    return Response(
        {
            "id": customer.id,
            "full_name": customer.full_name,
            "email": customer.email,
            "phone_number": customer.phone_number,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def set_customer_fcm_token(request, customer_id: int):
    """
    POST /customers/<customer_id>/fcm-token/
    Body: token (string) OR fcm_token (string)
    """
    token = (request.data.get("token") or request.data.get("fcm_token") or "").strip()
    if not token:
        return Response({"detail": "token is required."}, status=status.HTTP_400_BAD_REQUEST)
    try:
        customer = Customer.objects.get(pk=customer_id)
    except Customer.DoesNotExist:
        if FCM_DEBUG:
            logger.info("[FCM] set_customer_fcm_token customer not found customer_id=%s", customer_id)
        return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

    if FCM_DEBUG:
        logger.info("[FCM] set_customer_fcm_token saved customer_id=%s token_len=%s", customer_id, len(token))

    customer.fcm_token = token
    customer.fcm_token_updated_at = timezone.now()
    customer.save(update_fields=["fcm_token", "fcm_token_updated_at", "updated_at"])
    return Response({"detail": "Token saved."}, status=status.HTTP_200_OK)


@api_view(["POST"])
def clear_customer_fcm_token(request, customer_id: int):
    """
    POST /customers/<customer_id>/fcm-token/clear/
    Clears device token on logout.
    """
    try:
        customer = Customer.objects.get(pk=customer_id)
    except Customer.DoesNotExist:
        return Response({"detail": "Customer not found."}, status=status.HTTP_404_NOT_FOUND)

    if FCM_DEBUG:
        logger.info("[FCM] clear_customer_fcm_token cleared customer_id=%s", customer_id)

    customer.fcm_token = ""
    customer.fcm_token_updated_at = timezone.now()
    customer.save(update_fields=["fcm_token", "fcm_token_updated_at", "updated_at"])
    return Response({"detail": "Token cleared."}, status=status.HTTP_200_OK)
