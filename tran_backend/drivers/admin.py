from django.contrib import admin

from .models import Driver, DriverLocation, DriverRoute, VehicleType
from core.models import AdminSettings, VehicleTypeSettings


class DriverLocationInline(admin.StackedInline):
    model = DriverLocation
    extra = 0
    max_num = 1
    can_delete = True
    fields = (
        "latitude",
        "longitude",
        "is_online",
        "current_city",
        "current_area",
        "destination",
        "updated_at",
    )
    readonly_fields = ("updated_at",)


class DriverRouteInline(admin.TabularInline):
    model = DriverRoute
    extra = 0
    fields = (
        "destination_text",
        "destination_lat",
        "destination_lng",
        "available_from",
        "bid_amount",
        "is_active",
        "updated_at",
    )
    readonly_fields = ("updated_at",)


@admin.register(VehicleType)
class VehicleTypeAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)
    fields = ("name", "icon")

    def save_model(self, request, obj, form, change):
        # Prefill per-vehicle settings (including platform commission) when a new
        # vehicle type is created from Django Admin.
        is_new = obj.pk is None
        super().save_model(request, obj, form, change)

        if not is_new:
            return

        admin_settings = AdminSettings.get_settings()

        VehicleTypeSettings.objects.get_or_create(
            vehicle_type=obj,
            defaults={
                "short_distance_limit_km": admin_settings.short_distance_limit_km,
                "long_distance_limit_km": admin_settings.long_distance_limit_km,
                "pickup_radius_km": admin_settings.pickup_radius_km,
                "destination_radius_km": admin_settings.destination_radius_km,
                "base_fare_short_distance": admin_settings.base_fare_short_distance,
                "per_km_rate_short_distance": admin_settings.per_km_rate_short_distance,
                "per_km_rate_long_distance": admin_settings.per_km_rate_long_distance,
                "platform_commission_percentage": admin_settings.platform_commission_percentage,
                "surge_multiplier": admin_settings.surge_multiplier,
            },
        )


@admin.register(Driver)
class DriverAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "full_name",
        "phone_number",
        "vehicle_type",
        "truck_capacity",
        "is_online",
        "current_lat",
        "current_lng",
        "rating",
        "approved",
        "created_at",
    )
    search_fields = ("full_name", "email", "phone_number", "vehicle_number")
    list_filter = ("vehicle_type", "approved", "is_online", "created_at")
    inlines = [DriverLocationInline, DriverRouteInline]
    fieldsets = (
        (None, {"fields": ("full_name", "email", "phone_number", "password")}),
        (
            "Truck",
            {"fields": ("vehicle_number", "vehicle_type", "truck_capacity")},
        ),
        (
            "Documents",
            {"fields": ("license_image", "rc_book_image", "permit_image", "insurance_image")},
        ),
        (
            "Location",
            {
                "fields": (
                    "current_lat",
                    "current_lng",
                    "destination_lat",
                    "destination_lng",
                    "last_location_update",
                )
            },
        ),
        (
            "Availability",
            {"fields": ("is_online", "available_time", "rating", "approved")},
        ),
    )


@admin.register(DriverLocation)
class DriverLocationAdmin(admin.ModelAdmin):
    list_display = (
        "driver",
        "live_location",
        "is_online",
        "destination",
        "updated_at",
    )
    list_filter = ("is_online", "updated_at")
    search_fields = ("driver__full_name", "current_city", "current_area", "destination")
    readonly_fields = ("updated_at",)
    autocomplete_fields = ("driver",)

    def live_location(self, obj: DriverLocation) -> str:
        city = (obj.current_city or "").strip()
        area = (obj.current_area or "").strip()
        dest = (obj.destination or "").strip()

        location = city
        if area:
            location = f"{location} - {area}" if location else area

        if dest:
            # Helps admin trace where driver is going, without raw lat/lng.
            location = f"{location or '-'} → {dest}"

        return location or '-'

    live_location.short_description = "Live location"


@admin.register(DriverRoute)
class DriverRouteAdmin(admin.ModelAdmin):
    list_display = ("id", "driver", "destination_text", "available_from", "bid_amount", "is_active", "updated_at")
    list_filter = ("is_active", "updated_at")
    search_fields = ("driver__full_name", "destination_text", "current_text")
    autocomplete_fields = ("driver",)
    readonly_fields = ("created_at", "updated_at")
