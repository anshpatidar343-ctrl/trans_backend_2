import secrets
from decimal import Decimal

from datetime import timedelta
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from core.services.fare import FareService
from core.services.matching import MatchingService
from core.services.distance import haversine_km
from core.services.fcm import send_data_multicast, send_data_notification
from core.services.razorpay_gateway import create_order, verify_signature
from customers.models import Customer
from drivers.models import Driver, VehicleType

from .models import Booking, Payment, BookingDriverRequest
from .serializers import (
    CreateBookingSerializer,
    GetAvailableTrucksSerializer,
    FareEstimateSerializer,
    ConfirmBookingSerializer,
    AssignBookingSerializer,
    DriverCardSerializer,
    BookingResponseSerializer,
    CustomerBookingSerializer,
    CreatePaymentOrderSerializer,
    VerifyPaymentSerializer,
    CancelBookingSerializer,
)


def _active_booking_driver_ids():
    """Driver IDs that have an active booking (locked). Used to hide them from map and available trucks."""
    return Booking.objects.filter(
        booking_status__in=[
            Booking.STATUS_PENDING,
            Booking.STATUS_ACCEPTED,
            Booking.STATUS_DRIVER_ASSIGNED,
            Booking.STATUS_STARTED,
            Booking.STATUS_IN_TRANSIT,
        ],
        driver_id__isnull=False,
    ).values_list("driver_id", flat=True).distinct()


@api_view(["GET"])
def online_vehicles(request):
    """
    GET /online-vehicles/
    Returns list of online drivers with id, current_lat, current_lng, vehicle_type, full_name, vehicle_number
    for showing live vehicle locations on the map. Locked drivers (on a trip) are excluded.
    Uses Driver.current_lat/lng; if missing, falls back to DriverLocation.latitude/longitude so drivers
    who just went online or whose location is only in DriverLocation still appear.
    """
    busy_driver_ids = list(_active_booking_driver_ids())
    drivers = (
        Driver.objects.filter(
            is_online=True,
            is_available=True,
            route_locked=False,
        )
        .select_related("location")
        .exclude(id__in=busy_driver_ids)
    )
    type_icons = {}
    for vt in VehicleType.objects.all():
        try:
            if vt.icon:
                type_icons[vt.name.strip().lower()] = request.build_absolute_uri(vt.icon.url)
        except Exception:
            continue

    out = []
    for d in drivers:
        lat = d.current_lat
        lng = d.current_lng
        if (lat is None or lng is None or (lat == 0 and lng == 0)) and getattr(d, "location", None):
            loc = d.location
            lat = getattr(loc, "latitude", None)
            lng = getattr(loc, "longitude", None)
        if lat is None or lng is None or (lat == 0 and lng == 0):
            continue
        out.append({
            "id": d.id,
            "full_name": d.full_name,
            "vehicle_type": d.vehicle_type or "",
            "vehicle_icon_url": type_icons.get((d.vehicle_type or "").strip().lower(), ""),
            "vehicle_number": d.vehicle_number or "",
            "current_lat": float(lat),
            "current_lng": float(lng),
        })
    return Response({"vehicles": out}, status=status.HTTP_200_OK)


@api_view(["GET"])
def fare_estimate(request):
    """
    GET /fare-estimate?pickup_lat=...&pickup_lng=...&drop_lat=...&drop_lng=...
    Returns distance_km, estimated_fare, final_fare (with commission).
    """
    ser = FareEstimateSerializer(data=request.query_params)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    data = ser.validated_data
    pickup_lat = data["pickup_lat"]
    pickup_lng = data["pickup_lng"]
    drop_lat = data["drop_lat"]
    drop_lng = data["drop_lng"]
    truck_type = data.get("truck_type") or ""

    distance_km, driver_fare, final_fare = FareService.estimate_fare(
        pickup_lat, pickup_lng, drop_lat, drop_lng, truck_type=truck_type
    )
    return Response(
        {
            "distance_km": distance_km,
            "estimated_fare": float(driver_fare),
            "final_fare": float(final_fare),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def get_available_trucks(request):
    """
    POST /get-available-trucks
    Body: pickup_lat, pickup_lng, drop_lat, drop_lng, truck_type
    Returns list of driver cards (driver_name, truck_type, pickup_distance_km, ...).
    """
    ser = GetAvailableTrucksSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    data = ser.validated_data

    # Only show drivers who are available, not route-locked, and not on an active booking.
    busy_driver_ids = list(_active_booking_driver_ids())
    drivers = (
        Driver.objects.filter(is_online=True, is_available=True, route_locked=False)
        .exclude(id__in=busy_driver_ids)
        .select_related("location")
        .prefetch_related("routes")
    )
    booking_time = data.get("booking_time") or timezone.now()
    matches = MatchingService.filter_and_sort_drivers(
        drivers,
        data["pickup_lat"],
        data["pickup_lng"],
        data["drop_lat"],
        data["drop_lng"],
        data["truck_type"],
        booking_time,
    )

    truck_type = data["truck_type"]
    distance_km, _, final_fare = FareService.estimate_fare(
        data["pickup_lat"],
        data["pickup_lng"],
        data["drop_lat"],
        data["drop_lng"],
        truck_type=truck_type,
    )

    cards = []
    for driver, pickup_dist, dest_dist in matches:
        destination_text = ""
        try:
            destination_text = getattr(getattr(driver, "location", None), "destination", "") or ""
        except Exception:
            destination_text = ""
        cards.append(
            {
                "driver_id": driver.id,
                "driver_name": driver.full_name,
                "truck_type": driver.vehicle_type or "",
                "truck_number": driver.vehicle_number or "",
                "pickup_distance_km": pickup_dist,
                "destination_distance_km": dest_dist,
                "destination": destination_text,
                "available_time": driver.available_time,
                "estimated_fare": float(final_fare),
                "rating": driver.rating,
            }
        )

    return Response({"available_trucks": cards}, status=status.HTTP_200_OK)


@api_view(["POST"])
def create_booking(request):
    """
    POST /create-booking
    Body: user_id, pickup_lat, pickup_lng, drop_lat, drop_lng, pickup_city?, drop_city?, truck_type
    Creates booking with status=pending, calculates distance and estimated_fare.
    """
    ser = CreateBookingSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    data = ser.validated_data

    try:
        user = Customer.objects.get(pk=data["user_id"])
    except Customer.DoesNotExist:
        return Response(
            {"detail": "User not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Users can have multiple active bookings (e.g. multiple trucks for different loads).
    # Drivers are still limited to one active trip at a time (enforced in assign_booking / accept_booking).

    distance_km, _, final_fare = FareService.estimate_fare(
        data["pickup_lat"],
        data["pickup_lng"],
        data["drop_lat"],
        data["drop_lng"],
        truck_type=data["truck_type"],
    )

    load_type = (
        (data.get("load_type") or "").strip()
        or (request.data.get("load_type") or "").strip()
        or (request.data.get("loadType") or "").strip()
    )

    otp = f"{secrets.randbelow(10000):04d}"

    booking_time = data.get("booking_time") or timezone.now()

    booking = Booking.objects.create(
        user=user,
        pickup_lat=data["pickup_lat"],
        pickup_lng=data["pickup_lng"],
        drop_lat=data["drop_lat"],
        drop_lng=data["drop_lng"],
        pickup_city=data.get("pickup_city", ""),
        drop_city=data.get("drop_city", ""),
        truck_type=data["truck_type"],
        load_type=load_type,
        distance_km=distance_km,
        estimated_fare=final_fare,
        booking_status=Booking.STATUS_PENDING,
        pickup_otp=otp,
        booking_time=booking_time,
        search_started_at=timezone.now(),
        search_expires_at=timezone.now() + timedelta(seconds=120),
    )

    # Option A: Dispatch first batch; the matching worker sends next batches if needed.
    try:
        drivers_qs = (
            Driver.objects.filter(is_online=True, is_available=True, route_locked=False)
            .select_related("location")
            .prefetch_related("routes")
        )
        matches = MatchingService.filter_and_sort_drivers(
            drivers_qs,
            data["pickup_lat"],
            data["pickup_lng"],
            data["drop_lat"],
            data["drop_lng"],
            data["truck_type"],
            booking.booking_time,
        )
        batch_size = 3
        first_batch = matches[:batch_size]
        tokens = []
        for d, _, _ in first_batch:
            # Track that we sent this booking request to this driver.
            BookingDriverRequest.objects.get_or_create(
                booking=booking,
                driver=d,
                defaults={"status": BookingDriverRequest.STATUS_SENT},
            )
            tk = (getattr(d, "fcm_token", "") or "").strip()
            if tk:
                tokens.append(tk)

        if tokens:
            booking.last_batch_sent_at = timezone.now()
            booking.save(update_fields=["last_batch_sent_at", "updated_at"])
            send_data_multicast(
                tokens=tokens,
                data={
                    "type": "NEW_BOOKING",
                    "booking_id": str(booking.id),
                    "pickup_lat": str(booking.pickup_lat),
                    "pickup_lng": str(booking.pickup_lng),
                    "drop_lat": str(booking.drop_lat),
                    "drop_lng": str(booking.drop_lng),
                    "truck_type": booking.truck_type or "",
                    "pickup_city": booking.pickup_city or "",
                    "drop_city": booking.drop_city or "",
                    "load_type": booking.load_type or "",
                    "distance_km": str(booking.distance_km or 0.0),
                    "estimated_fare": str(booking.estimated_fare or ""),
                },
                android_channel_id="booking_alerts_v2",
            )
    except Exception:
        # Booking creation must not fail due to push errors.
        pass

    return Response(
        BookingResponseSerializer(booking).data,
        status=status.HTTP_201_CREATED,
    )


@api_view(["POST"])
def confirm_booking(request):
    """
    POST /confirm-booking
    Body: booking_id
    User confirms the booking (keeps status as pending until driver accepts; or can mean "confirmed" state).
    Returns booking details.
    """
    ser = ConfirmBookingSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

    try:
        booking = Booking.objects.get(pk=ser.validated_data["booking_id"])
    except Booking.DoesNotExist:
        return Response(
            {"detail": "Booking not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    if booking.booking_status != Booking.STATUS_PENDING:
        return Response(
            {"detail": "Booking is already confirmed or in progress."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    return Response(
        BookingResponseSerializer(booking).data,
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def assign_booking(request):
    """
    POST /assign-booking
    Body: booking_id, driver_id

    Customer selects a driver; we assign driver to booking (status stays pending).
    Driver will accept -> status accepted and driver lock will apply.
    """
    ser = AssignBookingSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)

    booking_id = ser.validated_data["booking_id"]
    driver_id = ser.validated_data["driver_id"]

    try:
        booking = Booking.objects.get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)
    try:
        driver = Driver.objects.get(pk=driver_id)
    except Driver.DoesNotExist:
        return Response({"detail": "Driver not found."}, status=status.HTTP_404_NOT_FOUND)

    # Prevent multiple bookings for same driver (active trip/request).
    active_driver_statuses = [
        Booking.STATUS_PENDING,
        Booking.STATUS_ACCEPTED,
        Booking.STATUS_DRIVER_ASSIGNED,
        Booking.STATUS_STARTED,
        Booking.STATUS_IN_TRANSIT,
    ]
    if (not getattr(driver, "is_available", True)) or Booking.objects.filter(
        driver=driver, booking_status__in=active_driver_statuses
    ).exists():
        return Response(
            {"detail": "Driver is not available right now."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if booking.booking_status not in [Booking.STATUS_PENDING, Booking.STATUS_DRIVER_ASSIGNED]:
        return Response(
            {"detail": "Booking cannot be assigned in current state."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    booking.driver = driver
    booking.booking_status = Booking.STATUS_PENDING
    # keep fares if already calculated
    if booking.final_fare is None and booking.estimated_fare is not None:
        booking.final_fare = booking.estimated_fare
    booking.save()

    # If customer selected a specific driver, notify that driver immediately.
    try:
        token = (getattr(driver, "fcm_token", "") or "").strip()
        if token:
            send_data_notification(
                token=token,
                data={
                    "type": "NEW_BOOKING",
                    "booking_id": str(booking.id),
                    "pickup_lat": str(booking.pickup_lat),
                    "pickup_lng": str(booking.pickup_lng),
                    "drop_lat": str(booking.drop_lat),
                    "drop_lng": str(booking.drop_lng),
                    "truck_type": booking.truck_type or "",
                    "pickup_city": booking.pickup_city or "",
                    "drop_city": booking.drop_city or "",
                    "load_type": booking.load_type or "",
                    "distance_km": str(booking.distance_km or 0.0),
                    "estimated_fare": str(booking.estimated_fare or ""),
                },
                android_channel_id="booking_alerts_v2",
            )
    except Exception:
        pass

    return Response(BookingResponseSerializer(booking).data, status=status.HTTP_200_OK)


@api_view(["POST"])
def create_payment_order(request):
    """
    POST /create-payment-order
    Body: booking_id
    Creates Razorpay order for 10% advance (INR).
    """
    ser = CreatePaymentOrderSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    booking_id = int(ser.validated_data["booking_id"])

    try:
        booking = Booking.objects.select_related("user", "driver").get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.booking_status != Booking.STATUS_AWAITING_PAYMENT:
        return Response({"detail": "Booking is not awaiting payment."}, status=status.HTTP_400_BAD_REQUEST)
    if booking.is_payment_expired():
        return Response({"detail": "Payment window expired."}, status=status.HTTP_400_BAD_REQUEST)

    final_fare = Decimal(str(booking.final_fare or booking.estimated_fare or 0))
    if final_fare <= 0:
        return Response({"detail": "Fare not available."}, status=status.HTTP_400_BAD_REQUEST)
    advance = (final_fare * Decimal("0.10")).quantize(Decimal("0.01"))
    booking.advance_amount = advance
    booking.payment_status = "pending"
    booking.save(update_fields=["advance_amount", "payment_status", "updated_at"])

    amount_paise = int(advance * 100)
    order = create_order(
        amount_paise=amount_paise,
        receipt=f"booking_{booking.id}",
        notes={"booking_id": str(booking.id), "user_id": str(booking.user_id)},
    )

    Payment.objects.create(
        booking=booking,
        razorpay_order_id=str(order.get("id") or ""),
        amount=advance,
        status=Payment.STATUS_PENDING,
    )

    return Response(
        {
            "booking_id": booking.id,
            "razorpay_order_id": order.get("id"),
            "amount": float(advance),
            "amount_paise": amount_paise,
            "currency": "INR",
            "payment_due_at": booking.payment_due_at.isoformat() if booking.payment_due_at else None,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
def verify_payment(request):
    """
    POST /verify-payment
    Body: booking_id, razorpay_order_id, razorpay_payment_id, razorpay_signature

    If verified:
      - Payment -> success
      - Booking -> driver_assigned
      - Notify driver: payment_success
    """
    ser = VerifyPaymentSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    data = ser.validated_data
    booking_id = int(data["booking_id"])

    try:
        booking = Booking.objects.select_related("driver", "user").get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.booking_status != Booking.STATUS_AWAITING_PAYMENT:
        return Response({"detail": "Booking is not awaiting payment."}, status=status.HTTP_400_BAD_REQUEST)
    if booking.is_payment_expired():
        return Response({"detail": "Payment window expired."}, status=status.HTTP_400_BAD_REQUEST)
    if booking.driver_id is None:
        return Response({"detail": "No driver assigned."}, status=status.HTTP_400_BAD_REQUEST)

    ok = verify_signature(
        order_id=str(data["razorpay_order_id"]),
        payment_id=str(data["razorpay_payment_id"]),
        signature=str(data["razorpay_signature"]),
    )
    if not ok:
        # Mark failed
        Payment.objects.create(
            booking=booking,
            razorpay_order_id=str(data["razorpay_order_id"]),
            razorpay_payment_id=str(data["razorpay_payment_id"]),
            razorpay_signature=str(data["razorpay_signature"]),
            amount=Decimal(str(booking.advance_amount or 0)),
            status=Payment.STATUS_FAILED,
        )
        booking.payment_status = "failed"
        booking.booking_status = Booking.STATUS_CANCELLED
        booking.save(update_fields=["payment_status", "booking_status", "updated_at"])
        # Notify driver cancel + unlock
        try:
            d = booking.driver
            if d:
                d.is_available = True
                d.route_locked = False
                d.save(update_fields=["is_available", "route_locked", "updated_at"])
                tk = (getattr(d, "fcm_token", "") or "").strip()
                if tk:
                    send_notification(
                        token=tk,
                        title="Booking cancelled",
                        body="Payment verification failed.",
                        data={"type": "booking_cancel", "booking_id": str(booking.id)},
                        android_channel_id="booking_alerts_v2",
                    )
        except Exception:
            pass
        return Response({"detail": "Payment verification failed."}, status=status.HTTP_400_BAD_REQUEST)

    # Verified success
    Payment.objects.create(
        booking=booking,
        razorpay_order_id=str(data["razorpay_order_id"]),
        razorpay_payment_id=str(data["razorpay_payment_id"]),
        razorpay_signature=str(data["razorpay_signature"]),
        amount=Decimal(str(booking.advance_amount or 0)),
        status=Payment.STATUS_SUCCESS,
    )
    booking.payment_status = "success"
    booking.booking_status = Booking.STATUS_DRIVER_ASSIGNED
    booking.save(update_fields=["payment_status", "booking_status", "updated_at"])

    # Notify driver payment success
    try:
        d = booking.driver
        if d:
            tk = (getattr(d, "fcm_token", "") or "").strip()
            if tk:
                send_notification(
                    token=tk,
                    title="Payment received",
                    body="Customer paid advance. Start trip.",
                    data={"type": "payment_success", "booking_id": str(booking.id)},
                    android_channel_id="general",
                )
    except Exception:
        pass

    return Response(BookingResponseSerializer(booking).data, status=status.HTTP_200_OK)


@api_view(["POST"])
def cancel_booking(request):
    """
    POST /cancel-booking
    Body: booking_id, reason?
    Cancels booking and releases driver.
    """
    ser = CancelBookingSerializer(data=request.data)
    if not ser.is_valid():
        return Response(ser.errors, status=status.HTTP_400_BAD_REQUEST)
    booking_id = int(ser.validated_data["booking_id"])

    try:
        booking = Booking.objects.select_related("driver").get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    booking.booking_status = Booking.STATUS_CANCELLED
    booking.payment_status = "failed" if booking.booking_status == Booking.STATUS_AWAITING_PAYMENT else booking.payment_status
    booking.save(update_fields=["booking_status", "payment_status", "updated_at"])

    # Release driver + notify cancel
    try:
        d = booking.driver
        if d:
            d.is_available = True
            d.route_locked = False
            d.save(update_fields=["is_available", "route_locked", "updated_at"])
            tk = (getattr(d, "fcm_token", "") or "").strip()
            if tk:
                send_notification(
                    token=tk,
                    title="Booking cancelled",
                    body="Customer cancelled / payment timeout.",
                    data={"type": "booking_cancel", "booking_id": str(booking.id)},
                    android_channel_id="booking_alerts_v2",
                )
    except Exception:
        pass

    return Response({"detail": "Cancelled.", "booking_id": booking.id}, status=status.HTTP_200_OK)


@api_view(["GET"])
def user_bookings(request, user_id: int):
    """
    GET /user-bookings/<user_id>/
    Returns all bookings for a customer, newest first.
    """
    qs = Booking.objects.filter(user_id=user_id).select_related("driver").order_by("-created_at")
    return Response(
        {"bookings": CustomerBookingSerializer(qs, many=True).data},
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
def booking_detail(request, booking_id: int):
    """
    GET /booking/<booking_id>/
    Returns booking details.
    """
    try:
        booking = Booking.objects.select_related("driver").get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)
    return Response(CustomerBookingSerializer(booking).data, status=status.HTTP_200_OK)


@api_view(["GET"])
def payment_history(request, user_id: int):
    """
    GET /payment-history/<user_id>/
    For now: payments are derived from completed bookings.
    """
    qs = (
        Booking.objects.filter(user_id=user_id, booking_status=Booking.STATUS_COMPLETED)
        .select_related("driver")
        .order_by("-updated_at")
    )
    return Response(
        {"payments": CustomerBookingSerializer(qs, many=True).data},
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
def booking_live_location(request, booking_id: int):
    """
    GET /booking-live/<booking_id>/
    Returns driver current location for live tracking while booking is live.
    Live statuses: accepted, driver_assigned, started, in_transit
    """
    try:
        booking = Booking.objects.select_related("driver").get(pk=booking_id)
    except Booking.DoesNotExist:
        return Response({"detail": "Booking not found."}, status=status.HTTP_404_NOT_FOUND)

    if booking.driver_id is None:
        return Response({"detail": "Driver not assigned yet."}, status=status.HTTP_400_BAD_REQUEST)

    live_statuses = [
        Booking.STATUS_ACCEPTED,
        Booking.STATUS_DRIVER_ASSIGNED,
        Booking.STATUS_STARTED,
        Booking.STATUS_IN_TRANSIT,
    ]
    if booking.booking_status not in live_statuses:
        return Response(
            {"detail": "Tracking not available for this booking.", "booking_status": booking.booking_status},
            status=status.HTTP_400_BAD_REQUEST,
        )

    d = booking.driver
    if d is None or d.current_lat is None or d.current_lng is None:
        return Response({"detail": "Driver location unavailable."}, status=status.HTTP_404_NOT_FOUND)

    # include optional icon URL for UI marker
    icon_url = ""
    try:
        vt = VehicleType.objects.filter(name__iexact=(d.vehicle_type or "").strip()).first()
        if vt and vt.icon:
            icon_url = request.build_absolute_uri(vt.icon.url)
    except Exception:
        icon_url = ""

    return Response(
        {
            "booking_id": booking.id,
            "booking_status": booking.booking_status,
            "driver_id": d.id,
            "driver_name": d.full_name,
            "vehicle_type": d.vehicle_type or "",
            "vehicle_number": d.vehicle_number or "",
            "vehicle_icon_url": icon_url,
            "current_lat": float(d.current_lat),
            "current_lng": float(d.current_lng),
            "last_location_update": d.last_location_update,
        },
        status=status.HTTP_200_OK,
    )
