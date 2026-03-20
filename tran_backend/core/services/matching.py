from datetime import datetime
from typing import List, Optional, Tuple

from django.utils import timezone

from core.models import AdminSettings, get_settings_for_vehicle_type
from core.services.distance import haversine_km


class MatchingService:
    """
    Driver matching using admin-defined pickup_radius_km, destination_radius_km
    (per vehicle type when set), and driver available_time vs booking_time.
    """

    @staticmethod
    def get_settings() -> AdminSettings:
        return AdminSettings.get_settings()

    @classmethod
    def pickup_distance_km(
        cls,
        driver_lat: float,
        driver_lng: float,
        pickup_lat: float,
        pickup_lng: float,
    ) -> float:
        """Distance from driver current location to user pickup."""
        return haversine_km(driver_lat, driver_lng, pickup_lat, pickup_lng)

    @classmethod
    def destination_distance_km(
        cls,
        driver_dest_lat: float,
        driver_dest_lng: float,
        drop_lat: float,
        drop_lng: float,
    ) -> float:
        """Distance from driver's destination to user drop."""
        return haversine_km(
            driver_dest_lat, driver_dest_lng, drop_lat, drop_lng
        )

    @classmethod
    def filter_and_sort_drivers(
        cls,
        drivers_queryset,
        pickup_lat: float,
        pickup_lng: float,
        drop_lat: float,
        drop_lng: float,
        truck_type: str,
        booking_time: Optional[datetime] = None,
        pickup_radius_multiplier: float = 1.0,
    ) -> List[Tuple[any, float, float]]:
        """
        Filter drivers that are online, match truck_type, and satisfy:
        - pickup_distance <= pickup_radius_km
        - destination_distance <= destination_radius_km
        - driver_available_time <= booking_time (if both set)

        Returns list of (driver, pickup_distance_km, destination_distance_km)
        sorted by pickup_distance ascending.
        """
        settings = get_settings_for_vehicle_type(truck_type or "")
        booking_time = booking_time or timezone.now()
        pickup_radius_multiplier = float(pickup_radius_multiplier or 1.0)
        if pickup_radius_multiplier <= 0:
            pickup_radius_multiplier = 1.0
        effective_pickup_radius_km = float(settings.pickup_radius_km) * pickup_radius_multiplier

        candidates = []
        for driver in drivers_queryset:
            if not getattr(driver, "is_online", True):
                continue
            # Driver lock system: busy / locked drivers should not appear.
            if getattr(driver, "is_available", True) is False:
                continue
            if getattr(driver, "route_locked", False):
                continue
            dt = getattr(driver, "truck_type", None) or getattr(
                driver, "vehicle_type", ""
            )
            if truck_type and dt and dt.strip().lower() != truck_type.strip().lower():
                continue

            driver_lat = getattr(driver, "current_lat", None) or getattr(
                driver, "current_latitude", None
            )
            driver_lng = getattr(driver, "current_lng", None) or getattr(
                driver, "current_longitude", None
            )
            if driver_lat is None or driver_lng is None:
                loc = getattr(driver, "location", None)
                if loc is not None and getattr(loc, "latitude", None) is not None and getattr(loc, "longitude", None) is not None:
                    driver_lat = loc.latitude
                    driver_lng = loc.longitude
                else:
                    continue

            pickup_dist = cls.pickup_distance_km(
                float(driver_lat), float(driver_lng), pickup_lat, pickup_lng
            )
            if pickup_dist > effective_pickup_radius_km:
                continue

            # Route-based matching:
            # - If driver has active routes -> match against any route.
            # - If driver has no routes -> fallback to legacy single-destination fields.
            best_dest_dist: Optional[float] = None

            routes = []
            try:
                routes = list(getattr(driver, "routes", []).filter(is_active=True))  # type: ignore[attr-defined]
            except Exception:
                routes = []

            if routes:
                for r in routes:
                    anywhere_route = r.destination_lat is None or r.destination_lng is None
                    # Free driver / anywhere: destination not set -> skip destination radius check (treat as pass).
                    if anywhere_route:
                        dest_dist = 0.0
                    else:
                        dest_dist = cls.destination_distance_km(
                            float(r.destination_lat), float(r.destination_lng), drop_lat, drop_lng
                        )
                        if dest_dist > float(settings.destination_radius_km):
                            continue

                    available_from = getattr(r, "available_from", None)
                    # For "Anywhere" routes we ignore available_from when matching because
                    # drivers are considered online/available for pickup now.
                    # Otherwise a future scheduled time blocks matching and prevents requests.
                    if (
                        not anywhere_route
                        and available_from is not None
                        and booking_time
                        and available_from > booking_time
                    ):
                        continue

                    if best_dest_dist is None or dest_dist < best_dest_dist:
                        best_dest_dist = dest_dist
            else:
                dest_lat = getattr(driver, "destination_lat", None)
                dest_lng = getattr(driver, "destination_lng", None)
                # No destination set -> treat as free driver (skip destination filter)
                if dest_lat is None or dest_lng is None:
                    best_dest_dist = 0.0
                else:
                    dest_dist = cls.destination_distance_km(
                        float(dest_lat), float(dest_lng), drop_lat, drop_lng
                    )
                    if dest_dist <= float(settings.destination_radius_km):
                        best_dest_dist = dest_dist

                available_time = getattr(driver, "available_time", None)
                if available_time is not None and booking_time and available_time > booking_time:
                    best_dest_dist = None

            if best_dest_dist is None:
                continue

            candidates.append((driver, round(pickup_dist, 2), round(float(best_dest_dist), 2)))

        candidates.sort(key=lambda x: x[1])
        return candidates
