from decimal import Decimal
from typing import Optional, Tuple

from core.models import AdminSettings, get_settings_for_vehicle_type
from core.services.distance import haversine_km


class FareService:
    """Fare calculation using admin-configured pricing (per vehicle type or global)."""

    @staticmethod
    def get_settings() -> AdminSettings:
        return AdminSettings.get_settings()

    @classmethod
    def trip_distance_km(
        cls,
        pickup_lat: float,
        pickup_lng: float,
        drop_lat: float,
        drop_lng: float,
    ) -> float:
        """Calculate trip distance in km (Haversine)."""
        return haversine_km(pickup_lat, pickup_lng, drop_lat, drop_lng)

    @classmethod
    def estimate_fare(
        cls,
        pickup_lat: float,
        pickup_lng: float,
        drop_lat: float,
        drop_lng: float,
        apply_surge: bool = True,
        truck_type: Optional[str] = None,
    ) -> Tuple[float, float, Decimal]:
        """
        Returns (distance_km, estimated_fare_before_commission, final_fare_for_user).
        Uses per-vehicle-type settings if truck_type is given and configured; else global AdminSettings.
        """
        settings = get_settings_for_vehicle_type(truck_type or "")
        distance_km = cls.trip_distance_km(
            pickup_lat, pickup_lng, drop_lat, drop_lng
        )

        if distance_km <= float(settings.short_distance_limit_km):
            base = float(settings.base_fare_short_distance)
            rate = float(settings.per_km_rate_short_distance)
            driver_fare = base + (distance_km * rate)
        else:
            rate = float(settings.per_km_rate_long_distance)
            driver_fare = distance_km * rate

        if apply_surge and getattr(settings, "surge_multiplier", None) and float(settings.surge_multiplier) > 1.0:
            driver_fare *= float(settings.surge_multiplier)

        driver_fare_decimal = Decimal(str(round(driver_fare, 2)))
        commission_pct = float(settings.platform_commission_percentage) / 100.0
        commission = driver_fare_decimal * Decimal(str(commission_pct))
        total_user_fare = driver_fare_decimal + commission

        return (round(distance_km, 2), driver_fare, total_user_fare)

    @classmethod
    def apply_commission(
        cls, driver_fare: Decimal, truck_type: Optional[str] = None
    ) -> Tuple[Decimal, Decimal]:
        """Given driver fare, return (platform_commission, total_user_price)."""
        settings = get_settings_for_vehicle_type(truck_type or "")
        pct = Decimal(str(settings.platform_commission_percentage)) / Decimal(
            "100"
        )
        commission = (driver_fare * pct).quantize(Decimal("0.01"))
        total_user = driver_fare + commission
        return commission, total_user
