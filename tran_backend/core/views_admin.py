from decimal import Decimal
from django.db.models import Sum, Count
from rest_framework import status
from rest_framework.decorators import api_view
from rest_framework.response import Response

from drivers.models import Driver
from bookings.models import Booking

from .models import AdminSettings


def _settings_to_dict(settings: AdminSettings) -> dict:
    return {
        "short_distance_limit_km": settings.short_distance_limit_km,
        "long_distance_limit_km": settings.long_distance_limit_km,
        "pickup_radius_km": settings.pickup_radius_km,
        "destination_radius_km": settings.destination_radius_km,
        "base_fare_short_distance": float(settings.base_fare_short_distance),
        "per_km_rate_short_distance": float(settings.per_km_rate_short_distance),
        "per_km_rate_long_distance": float(settings.per_km_rate_long_distance),
        "platform_commission_percentage": settings.platform_commission_percentage,
        "surge_multiplier": settings.surge_multiplier,
        "driver_location_update_interval": settings.driver_location_update_interval,
        "enable_driver_bidding": settings.enable_driver_bidding,
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


@api_view(["GET"])
def platform_settings(request):
    """
    GET /platform-settings
    Returns current AdminSettings (read-only for API; edit in Django Admin).
    """
    settings = AdminSettings.get_settings()
    return Response(_settings_to_dict(settings), status=status.HTTP_200_OK)


@api_view(["POST"])
def update_platform_settings(request):
    """
    POST /update-platform-settings
    Body: any subset of AdminSettings fields.
    Updates the singleton AdminSettings row.
    """
    settings = AdminSettings.get_settings()
    allowed = [
        "short_distance_limit_km",
        "long_distance_limit_km",
        "pickup_radius_km",
        "destination_radius_km",
        "base_fare_short_distance",
        "per_km_rate_short_distance",
        "per_km_rate_long_distance",
        "platform_commission_percentage",
        "surge_multiplier",
        "driver_location_update_interval",
        "enable_driver_bidding",
    ]
    for key in allowed:
        if key in request.data:
            setattr(settings, key, request.data[key])
    settings.save()
    return Response(_settings_to_dict(settings), status=status.HTTP_200_OK)


@api_view(["GET"])
def booking_analytics(request):
    """
    GET /booking-analytics
    Returns booking counts by status, total revenue, completed count, etc.
    """
    completed = Booking.objects.filter(booking_status=Booking.STATUS_COMPLETED)
    total_revenue = completed.aggregate(s=Sum("final_fare"))["s"] or Decimal("0")
    commission_pct = AdminSettings.get_settings().platform_commission_percentage
    platform_revenue = total_revenue * (Decimal(str(commission_pct)) / Decimal("100"))

    by_status = (
        Booking.objects.values("booking_status")
        .annotate(count=Count("id"))
        .order_by("booking_status")
    )

    return Response(
        {
            "total_bookings": Booking.objects.count(),
            "completed_bookings": completed.count(),
            "cancelled_bookings": Booking.objects.filter(
                booking_status=Booking.STATUS_CANCELLED
            ).count(),
            "by_status": list(by_status),
            "total_revenue_user_facing": float(total_revenue),
            "platform_commission_percentage": commission_pct,
            "platform_revenue": float(platform_revenue),
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
def driver_analytics(request):
    """
    GET /driver-analytics
    Returns driver counts (total, online, approved), etc.
    """
    total = Driver.objects.count()
    online = Driver.objects.filter(is_online=True).count()
    approved = Driver.objects.filter(approved=True).count()

    return Response(
        {
            "total_drivers": total,
            "online_drivers": online,
            "approved_drivers": approved,
        },
        status=status.HTTP_200_OK,
    )
