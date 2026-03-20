from datetime import timedelta

from decimal import Decimal
from django.utils import timezone
from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.decorators import api_view, authentication_classes, permission_classes
from rest_framework.response import Response

from drivers.models import Driver
from core.services.fcm import send_multicast
from core.authentication.jwt_authentication import JWTAuthentication
from core.permissions import IsDriverAuthenticated

from .models import Booking, BookingDriverRequest
from .serializers import BookingResponseSerializer, VerifyOtpSerializer, SmartUnlockSerializer
from core.services.distance import haversine_km


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def driver_online(request):
    """
    POST /driver-online
    Body: driver_id, is_online (bool), available_time? (ISO datetime), destination_lat?, destination_lng?
    """
    driver_id = request.data.get("driver_id")
    if driver_id is None:
        return Response(
            {"detail": "driver_id is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    # Safety: auto-unlock stale lock if driver has no active bookings.
    # This fixes cases where the app was killed / network failed and unlock never happened.
    try:
        active_driver_statuses = [
            Booking.STATUS_PENDING,
            Booking.STATUS_ACCEPTED,
            Booking.STATUS_AWAITING_PAYMENT,
            Booking.STATUS_DRIVER_ASSIGNED,
            Booking.STATUS_STARTED,
            Booking.STATUS_IN_TRANSIT,
        ]
        has_active = Booking.objects.filter(driver=driver, booking_status__in=active_driver_statuses).exists()
        if not has_active:
            if driver.route_locked or (driver.is_available is False):
                driver.route_locked = False
                driver.is_available = True
    except Exception:
        pass

    driver.is_online = request.data.get("is_online", True)
    if "available_time" in request.data and request.data["available_time"]:
        from django.utils.dateparse import parse_datetime
        at = parse_datetime(request.data["available_time"])
        driver.available_time = at
    if "destination_lat" in request.data:
        driver.destination_lat = request.data.get("destination_lat")
    if "destination_lng" in request.data:
        driver.destination_lng = request.data.get("destination_lng")

    driver.save()
    return Response(
        {
            "driver_id": driver.id,
            "is_online": driver.is_online,
            "available_time": driver.available_time,
            "destination_lat": driver.destination_lat,
            "destination_lng": driver.destination_lng,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def update_driver_location(request):
    """
    POST /update-driver-location
    Body: driver_id, current_lat, current_lng
    """
    driver_id = request.data.get("driver_id")
    current_lat = request.data.get("current_lat")
    current_lng = request.data.get("current_lng")
    if driver_id is None or current_lat is None or current_lng is None:
        return Response(
            {"detail": "driver_id, current_lat, current_lng are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user

    driver.current_lat = float(current_lat)
    driver.current_lng = float(current_lng)
    driver.last_location_update = timezone.now()
    driver.save(update_fields=["current_lat", "current_lng", "last_location_update", "updated_at"])

    return Response(
        {
            "driver_id": driver.id,
            "current_lat": driver.current_lat,
            "current_lng": driver.current_lng,
            "last_location_update": driver.last_location_update,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def accept_booking(request):
    """
    POST /accept-booking
    Body: driver_id, booking_id
    """
    driver_id = request.data.get("driver_id")
    booking_id = request.data.get("booking_id")
    if not driver_id or not booking_id:
        return Response(
            {"detail": "driver_id and booking_id are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    driver = request.user
    try:
        with transaction.atomic():
            booking = (
                Booking.objects.select_for_update()
                .select_related("user", "driver")
                .get(pk=booking_id)
            )

            # Booking must be pending.
            if booking.booking_status != Booking.STATUS_PENDING:
                return Response(
                    {"detail": "Booking is no longer pending."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # First-accept wins: if unassigned, assign now; if assigned, must match.
            if booking.driver_id is None:
                booking.driver = driver
            elif booking.driver_id != int(driver_id):
                return Response(
                    {"detail": "Booking is assigned to a different driver."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Prevent driver accepting multiple active bookings.
            active_driver_statuses = [
                Booking.STATUS_PENDING,
                Booking.STATUS_ACCEPTED,
                Booking.STATUS_DRIVER_ASSIGNED,
                Booking.STATUS_STARTED,
                Booking.STATUS_IN_TRANSIT,
            ]
            if (
                Booking.objects.filter(driver=driver, booking_status__in=active_driver_statuses)
                .exclude(pk=booking.id)
                .exists()
            ):
                return Response(
                    {"detail": "Driver already has an active booking."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            booking.booking_status = Booking.STATUS_ACCEPTED
            if booking.estimated_fare:
                booking.final_fare = booking.estimated_fare
            # Move to awaiting_payment state (5 min window)
            booking.booking_status = Booking.STATUS_AWAITING_PAYMENT
            booking.payment_status = "pending"
            booking.payment_due_at = timezone.now() + timedelta(minutes=5)
            if booking.final_fare is not None:
                # 10% advance
                booking.advance_amount = (booking.final_fare * Decimal("0.10")).quantize(Decimal("0.01"))
            booking.save(
                update_fields=[
                    "driver",
                    "booking_status",
                    "final_fare",
                    "advance_amount",
                    "payment_status",
                    "payment_due_at",
                    "updated_at",
                ]
            )

            # Track accept for Option A matching
            try:
                BookingDriverRequest.objects.update_or_create(
                    booking=booking,
                    driver=driver,
                    defaults={
                        "status": BookingDriverRequest.STATUS_ACCEPTED,
                        "responded_at": timezone.now(),
                    },
                )
                # Mark other outstanding requests as cancelled (best-effort).
                BookingDriverRequest.objects.filter(
                    booking=booking,
                    status=BookingDriverRequest.STATUS_SENT,
                ).exclude(driver=driver).update(
                    status=BookingDriverRequest.STATUS_CANCELLED,
                    responded_at=timezone.now(),
                )
            except Exception:
                pass

            # Driver lock
            driver.is_available = False
            driver.route_locked = True
            driver.save(update_fields=["is_available", "route_locked", "updated_at"])
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    # Notify customer to open payment screen (best effort).
    try:
        customer = booking.user
        token = (getattr(customer, "fcm_token", "") or "").strip()
        if token:
            from core.services.fcm import send_notification

            send_notification(
                token=token,
                title="Driver accepted",
                body="Please complete advance payment to confirm booking.",
                data={
                    "type": "booking_accept",
                    "booking_id": str(booking.id),
                },
                android_channel_id="general",
            )
    except Exception:
        pass

    # Cancel the alert for other nearby drivers (best effort).
    try:
        other_driver_ids = list(
            BookingDriverRequest.objects.filter(booking_id=booking.id)
            .exclude(driver_id=driver.id)
            .values_list("driver_id", flat=True)
        )
        other_tokens = list(
            Driver.objects.filter(id__in=other_driver_ids)
            .exclude(fcm_token="")
            .values_list("fcm_token", flat=True)
        )
        if other_tokens:
            send_multicast(
                tokens=other_tokens,
                title="Booking assigned",
                body="This booking was accepted by another driver.",
                data={"type": "booking_cancel", "booking_id": str(booking.id)},
                android_channel_id="booking_alerts_v2",
            )
    except Exception:
        pass

    return Response(
        BookingResponseSerializer(booking).data,
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def reject_booking(request):
    """
    POST /reject-booking
    Body: driver_id, booking_id
    """
    driver_id = request.data.get("driver_id")
    booking_id = request.data.get("booking_id")
    if not driver_id or not booking_id:
        return Response(
            {"detail": "driver_id and booking_id are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    # Only allow rejecting a pending request.
    if booking.booking_status != Booking.STATUS_PENDING:
        return Response(
            {"detail": "Booking cannot be rejected in current state."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Option A: record rejection even if booking was not assigned to this driver (broadcast).
    try:
        BookingDriverRequest.objects.update_or_create(
            booking=booking,
            driver_id=int(driver_id),
            defaults={
                "status": BookingDriverRequest.STATUS_REJECTED,
                "responded_at": timezone.now(),
            },
        )
    except Exception:
        pass

    # If this booking was explicitly assigned to this driver (rare), clear it.
    if booking.driver_id == int(driver_id):
        booking.driver = None
        booking.booking_status = Booking.STATUS_PENDING
        booking.save(update_fields=["driver", "booking_status", "updated_at"])

    # unlock driver if they were locked by this booking
    try:
        driver = Driver.objects.get(pk=int(driver_id))
        driver.is_available = True
        driver.route_locked = False
        driver.save(update_fields=["is_available", "route_locked", "updated_at"])
    except Exception:
        pass

    return Response(
        {"detail": "Booking rejected.", "booking_id": booking.id},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def start_trip(request):
    """
    POST /start-trip
    Body: driver_id, booking_id
    Sets booking_status=in_transit.
    """
    driver_id = request.data.get("driver_id")
    booking_id = request.data.get("booking_id")
    if not driver_id or not booking_id:
        return Response({"detail": "driver_id and booking_id are required."}, status=status.HTTP_400_BAD_REQUEST)

    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.driver_id != int(driver_id):
        return Response({"detail": "Booking is not assigned to this driver."}, status=status.HTTP_400_BAD_REQUEST)
    # Deprecated in favor of OTP-based start.
    return Response(
        {"detail": "Use verify-otp to start trip."},
        status=status.HTTP_400_BAD_REQUEST,
    )


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def verify_otp(request):
    """
    POST /verify-otp
    Body: driver_id, booking_id, otp (4-digit)
    If OTP matches booking.pickup_otp -> booking.status=started and trip can begin.
    """
    ser = VerifyOtpSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    driver_id = ser.validated_data["driver_id"]
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    booking_id = ser.validated_data["booking_id"]
    otp = str(ser.validated_data["otp"]).strip()

    try:
        booking = Booking.objects.select_related("driver").get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.driver_id != int(driver_id):
        return Response({"detail": "Booking is not assigned to this driver."}, status=status.HTTP_400_BAD_REQUEST)

    if booking.booking_status not in [Booking.STATUS_ACCEPTED, Booking.STATUS_DRIVER_ASSIGNED]:
        return Response({"detail": "OTP cannot be verified in current state."}, status=status.HTTP_400_BAD_REQUEST)

    if otp != (booking.pickup_otp or ""):
        booking.otp_attempts = int(getattr(booking, "otp_attempts", 0) or 0) + 1
        booking.save(update_fields=["otp_attempts", "updated_at"])
        return Response({"detail": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

    booking.booking_status = Booking.STATUS_STARTED
    booking.otp_verified_at = timezone.now()
    booking.save(update_fields=["booking_status", "otp_verified_at", "updated_at"])
    return Response(BookingResponseSerializer(booking).data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def complete_trip(request):
    """
    POST /complete-trip
    Body: driver_id, booking_id
    Sets booking_status=completed.
    """
    driver_id = request.data.get("driver_id")
    booking_id = request.data.get("booking_id")
    if not driver_id or not booking_id:
        return Response({"detail": "driver_id and booking_id are required."}, status=status.HTTP_400_BAD_REQUEST)
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.driver_id != int(driver_id):
        return Response({"detail": "Booking is not assigned to this driver."}, status=status.HTTP_400_BAD_REQUEST)
    if booking.booking_status not in [
        Booking.STATUS_ACCEPTED,
        Booking.STATUS_DRIVER_ASSIGNED,
        Booking.STATUS_STARTED,
        Booking.STATUS_IN_TRANSIT,
    ]:
        return Response({"detail": "Trip cannot be completed in current state."}, status=status.HTTP_400_BAD_REQUEST)

    booking.booking_status = Booking.STATUS_COMPLETED
    booking.save(update_fields=["booking_status", "updated_at"])

    # unlock driver after completion
    try:
        driver = Driver.objects.get(pk=int(driver_id))
        driver.is_available = True
        driver.route_locked = False
        driver.save(update_fields=["is_available", "route_locked", "updated_at"])
    except Exception:
        pass

    return Response(BookingResponseSerializer(booking).data, status=status.HTTP_200_OK)


@api_view(["POST"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def smart_unlock(request):
    """
    POST /smart-unlock
    Body: driver_id, booking_id, threshold_km? (default 25)

    If driver is within threshold_km of booking destination, unlock routes
    while trip is ongoing (driver remains unavailable until completed).
    """
    ser = SmartUnlockSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    driver_id = int(ser.validated_data["driver_id"])
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)
    booking_id = int(ser.validated_data["booking_id"])
    threshold_km = float(ser.validated_data.get("threshold_km") or 25.0)

    try:
        driver = Driver.objects.get(pk=driver_id)
    except Driver.DoesNotExist:
        return Response({"detail": "Driver not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.driver_id != driver_id:
        return Response({"detail": "Booking is not assigned to this driver."}, status=status.HTTP_400_BAD_REQUEST)

    if booking.booking_status not in [Booking.STATUS_STARTED, Booking.STATUS_IN_TRANSIT]:
        return Response({"detail": "Smart unlock is only for live trips."}, status=status.HTTP_400_BAD_REQUEST)

    if driver.current_lat is None or driver.current_lng is None:
        return Response({"detail": "Driver location unavailable."}, status=status.HTTP_400_BAD_REQUEST)

    dist = haversine_km(float(driver.current_lat), float(driver.current_lng), float(booking.drop_lat), float(booking.drop_lng))
    if dist > threshold_km:
        return Response(
            {"detail": "Too far from destination.", "distance_km": float(dist), "threshold_km": threshold_km},
            status=status.HTTP_400_BAD_REQUEST,
        )

    driver.route_locked = False
    driver.save(update_fields=["route_locked", "updated_at"])
    return Response({"detail": "Routes unlocked.", "distance_km": float(dist)}, status=status.HTTP_200_OK)


@api_view(["GET"])
@authentication_classes([JWTAuthentication])
@permission_classes([IsDriverAuthenticated])
def driver_bookings(request, driver_id: int):
    """
    GET /driver-bookings/<driver_id>/
    Returns:
      - bookings assigned to this driver (Booking.driver_id == driver_id), newest first
      - pending booking requests that were sent to this driver but not accepted yet
        (BookingDriverRequest.status == SENT while Booking.booking_status is still pending).
    """
    if int(driver_id) != int(getattr(request.user, "id", -1)):
        return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

    # distinct() avoids duplicates when a booking is both assigned and also has a request row.
    # Booking->BookingDriverRequest reverse relation is `driver_requests`.
    qs = Booking.objects.filter(
        Q(driver_id=driver_id)
        | Q(
            driver_requests__driver_id=driver_id,
            driver_requests__status=BookingDriverRequest.STATUS_SENT,
        )
    ).distinct()

    # Sort in Python to keep it DB-agnostic across backends (created_at ordering).
    bookings = sorted(list(qs), key=lambda b: b.created_at, reverse=True)
    return Response(
        {"bookings": BookingResponseSerializer(bookings, many=True).data},
        status=status.HTTP_200_OK,
    )
