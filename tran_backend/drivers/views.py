import os
import logging

from django.contrib.auth.hashers import check_password
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, parser_classes, authentication_classes, permission_classes
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import Driver, DriverLocation, DriverRoute, VehicleType
from .serializers import (
    DriverSignupSerializer,
    DriverLoginSerializer,
    DriverLocationSerializer,
    DriverRouteSerializer,
    DriverProfileSerializer,
    DriverUpdateSerializer,
    VehicleTypeSerializer,
)
from core.services.whatsapp_otp import send_whatsapp_otp, verify_whatsapp_otp, OtpSendResult
from django.contrib.auth.hashers import make_password

from core.authentication.jwt_authentication import JWTAuthentication
from core.permissions import IsDriverAuthenticated
from core.services.jwt_service import create_driver_access_token

logger = logging.getLogger(__name__)
FCM_DEBUG = os.environ.get("FCM_DEBUG", "false").lower() == "true"


@api_view(["POST"])
@parser_classes([JSONParser, FormParser, MultiPartParser])
def driver_signup(request):
    serializer = DriverSignupSerializer(data=request.data)
    if serializer.is_valid():
        driver = serializer.save()
        token = create_driver_access_token(driver_id=driver.id)
        return Response(
            {
                "id": driver.id,
                "full_name": driver.full_name,
                "email": driver.email,
                "phone_number": driver.phone_number,
                "approved": driver.approved,
                "access_token": token,
                "token_type": "Bearer",
            },
            status=status.HTTP_201_CREATED,
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
def driver_login(request):
    serializer = DriverLoginSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    phone_number = serializer.validated_data["phone_number"]
    password = serializer.validated_data["password"]

    try:
        driver = Driver.objects.get(phone_number=phone_number)
    except Driver.DoesNotExist:
        return Response(
            {"detail": "Invalid phone number or password."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not check_password(password, driver.password):
        return Response(
            {"detail": "Invalid phone number or password."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        {
            "id": driver.id,
            "full_name": driver.full_name,
            "email": driver.email,
            "phone_number": driver.phone_number,
            "approved": driver.approved,
            "access_token": create_driver_access_token(driver_id=driver.id),
            "token_type": "Bearer",
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def driver_send_whatsapp_otp(request):
    """
    POST /api/drivers/send-whatsapp-otp/
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

        if Driver.objects.filter(phone_number__in=list(variants)).exists():
            return Response(
                {"detail": "Driver already exists."},
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
def driver_verify_whatsapp_otp(request):
    """
    POST /api/drivers/verify-whatsapp-otp/
    Body: phone_number, purpose, otp_token, otp
    """
    phone_number = str(request.data.get("phone_number") or "").strip()
    purpose = str(request.data.get("purpose") or "").strip()
    otp_token = str(request.data.get("otp_token") or "").strip()
    otp = str(request.data.get("otp") or "").strip()

    if not phone_number or not otp_token or not otp:
        return Response(
            {"detail": "phone_number, otp_token and otp are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
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
def driver_reset_password_with_whatsapp_otp(request):
    """
    POST /api/drivers/reset-password-with-whatsapp-otp/
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
        return Response(
            {"detail": "phone_number, otp_token, otp and new_password are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    ok, msg = verify_whatsapp_otp(
        otp_token=otp_token,
        otp=otp,
        purpose=purpose,
        phone=phone_number,
    )
    if not ok:
        return Response({"verified": False, "detail": msg}, status=status.HTTP_400_BAD_REQUEST)

    try:
        driver = Driver.objects.get(phone_number=phone_number)
    except Driver.DoesNotExist:
        return Response({"detail": "Driver not found."}, status=status.HTTP_404_NOT_FOUND)

    driver.password = make_password(new_password)
    driver.save(update_fields=["password", "updated_at"])
    return Response({"detail": "Password reset successfully."}, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def set_driver_fcm_token(request, driver_id: int):
    """
    POST /drivers/<driver_id>/fcm-token/
    Body: token (string) OR fcm_token (string)
    """
    token = (request.data.get("token") or request.data.get("fcm_token") or "").strip()
    if not token:
        return Response({"detail": "token is required."}, status=status.HTTP_400_BAD_REQUEST)
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    if FCM_DEBUG:
        logger.info("[FCM] set_driver_fcm_token saved driver_id=%s token_len=%s", driver_id, len(token))

    driver.fcm_token = token
    driver.fcm_token_updated_at = timezone.now()
    driver.save(update_fields=["fcm_token", "fcm_token_updated_at", "updated_at"])
    return Response({"detail": "Token saved."}, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def clear_driver_fcm_token(request, driver_id: int):
    """
    POST /drivers/<driver_id>/fcm-token/clear/
    Clears device token on logout.
    """
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    if FCM_DEBUG:
        logger.info("[FCM] clear_driver_fcm_token cleared driver_id=%s", driver_id)

    driver.fcm_token = ""
    driver.fcm_token_updated_at = timezone.now()
    driver.save(update_fields=["fcm_token", "fcm_token_updated_at", "updated_at"])
    return Response({"detail": "Token cleared."}, status=status.HTTP_200_OK)


@api_view(["GET"])
def vehicle_types(request):
    types_qs = VehicleType.objects.all().order_by("name")
    serializer = VehicleTypeSerializer(types_qs, many=True, context={"request": request})
    return Response(serializer.data)


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def driver_status(request, driver_id: int):
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    return Response(
        {
            "id": driver.id,
            "full_name": driver.full_name,
            "email": driver.email,
            "phone_number": driver.phone_number,
            "approved": driver.approved,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def update_location(request, driver_id: int):
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    location, _ = DriverLocation.objects.get_or_create(driver=driver)

    serializer = DriverLocationSerializer(
        instance=location, data=request.data, partial=True
    )
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    serializer.save()

    # Sync to Driver so customer map and APIs see is_online and location.
    driver_updated = False
    if getattr(location, "latitude", None) is not None and getattr(location, "longitude", None) is not None:
        driver.current_lat = location.latitude
        driver.current_lng = location.longitude
        driver_updated = True
    # Always sync is_online from request so driver shows online when toggle is on.
    if "is_online" in request.data:
        driver.is_online = bool(request.data.get("is_online"))
        driver_updated = True
    elif hasattr(location, "is_online"):
        driver.is_online = location.is_online
        driver_updated = True
    if driver_updated:
        driver.save(update_fields=["current_lat", "current_lng", "is_online", "updated_at"])

    if "destination_lat" in request.data or "destination_lng" in request.data:
        driver.destination_lat = request.data.get("destination_lat")
        driver.destination_lng = request.data.get("destination_lng")
        driver.save(update_fields=["destination_lat", "destination_lng", "updated_at"])

    if "available_time" in request.data and request.data.get("available_time"):
        from django.utils.dateparse import parse_datetime
        at = parse_datetime(str(request.data["available_time"]))
        if at is not None:
            driver.available_time = at
            driver.save(update_fields=["available_time", "updated_at"])

    return Response(serializer.data, status=status.HTTP_200_OK)


@api_view(["GET", "POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def driver_routes(request, driver_id: int):
    """
    GET  /drivers/<driver_id>/routes/  -> list routes
    POST /drivers/<driver_id>/routes/  -> create route
    """
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    if request.method == "GET":
        qs = driver.routes.all().order_by("-is_active", "-updated_at")
        return Response(DriverRouteSerializer(qs, many=True).data, status=status.HTTP_200_OK)

    # Lock: driver cannot set new routes while on an accepted/live booking.
    if getattr(driver, "route_locked", False):
        return Response(
            {"detail": "Routes are locked while you are on a booking."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    payload = dict(request.data or {})
    payload["driver"] = driver.id
    ser = DriverRouteSerializer(data=payload)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    obj = ser.save()
    return Response(DriverRouteSerializer(obj).data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def delete_driver_route(request, driver_id: int, route_id: int):
    """
    DELETE /drivers/<driver_id>/routes/<route_id>/
    """
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user
    try:
        route = driver.routes.get(pk=route_id)
    except Exception:
        return Response({"detail": "Route not found."}, status=status.HTTP_404_NOT_FOUND)
    route.delete()
    return Response({"detail": "Deleted."}, status=status.HTTP_200_OK)


@api_view(["GET", "PATCH"])
@parser_classes([JSONParser, FormParser, MultiPartParser])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def driver_profile(request, driver_id: int):
    if int(getattr(request.user, "id", -1)) != int(driver_id):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = (
        Driver.objects.select_related("location")
        .prefetch_related("routes")
        .get(pk=driver_id)
    )

    if request.method == "PATCH":
        ser = DriverUpdateSerializer(instance=driver, data=request.data, partial=True)
        if not ser.is_valid():
            return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
        ser.save()
        # refresh from db for profile output
        driver = (
            Driver.objects.select_related("location")
            .prefetch_related("routes")
            .get(pk=driver_id)
        )

    return Response(
        DriverProfileSerializer(driver, context={"request": request}).data,
        status=status.HTTP_200_OK,
    )
