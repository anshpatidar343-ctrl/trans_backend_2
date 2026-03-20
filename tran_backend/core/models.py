from django.db import models


class VehicleTypeSettings(models.Model):
    """
    Per-vehicle-type configuration: different pricing and radii for Pickup,
    12 Wheeler, etc. One row per vehicle type.
    """
    vehicle_type = models.OneToOneField(
        "drivers.VehicleType",
        on_delete=models.CASCADE,
        related_name="type_settings",
        help_text="e.g. Pickup, 12 Wheeler, Container",
    )

    # Distance limits (km)
    short_distance_limit_km = models.FloatField(default=50.0)
    long_distance_limit_km = models.FloatField(default=500.0)
    pickup_radius_km = models.FloatField(default=30.0)
    destination_radius_km = models.FloatField(default=25.0)

    # Short distance pricing
    base_fare_short_distance = models.DecimalField(
        max_digits=10, decimal_places=2, default=100.00
    )
    per_km_rate_short_distance = models.DecimalField(
        max_digits=8, decimal_places=2, default=15.00
    )
    per_km_rate_long_distance = models.DecimalField(
        max_digits=8, decimal_places=2, default=25.00
    )

    platform_commission_percentage = models.FloatField(default=10.0)
    surge_multiplier = models.FloatField(default=1.0)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Vehicle type settings"
        verbose_name_plural = "Settings by vehicle type"

    def __str__(self) -> str:
        return f"Settings: {self.vehicle_type.name}"


class AdminSettings(models.Model):
    """
    Singleton model for platform-wide configuration.
    Admin controls pricing, matching radius, commission, and operational params.
    """

    # Distance limits (km)
    short_distance_limit_km = models.FloatField(
        default=50.0,
        help_text="Max distance (km) for short-distance city transport pricing.",
    )
    long_distance_limit_km = models.FloatField(
        default=500.0,
        help_text="Threshold beyond which long-distance pricing applies (informational).",
    )
    pickup_radius_km = models.FloatField(
        default=30.0,
        help_text="Max distance (km) from driver current location to user pickup.",
    )
    destination_radius_km = models.FloatField(
        default=25.0,
        help_text="Max distance (km) from driver destination to user drop.",
    )

    # Short distance pricing
    base_fare_short_distance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=100.00,
        help_text="Base fare for short distance (e.g. ₹100).",
    )
    per_km_rate_short_distance = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=15.00,
        help_text="Per km rate for short distance.",
    )

    # Long distance pricing
    per_km_rate_long_distance = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=25.00,
        help_text="Per km rate for long distance (no base fare).",
    )

    # Commission & surge
    platform_commission_percentage = models.FloatField(
        default=10.0,
        help_text="Platform commission % (e.g. 10 = 10%).",
    )
    surge_multiplier = models.FloatField(
        default=1.0,
        help_text="Surge multiplier (1.0 = no surge).",
    )

    # Operational
    driver_location_update_interval = models.PositiveIntegerField(
        default=15,
        help_text="Expected driver location update interval in seconds (e.g. 10–15).",
    )
    enable_driver_bidding = models.BooleanField(
        default=False,
        help_text="Allow drivers to bid on bookings.",
    )

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Admin settings"
        verbose_name_plural = "Admin settings"

    def __str__(self) -> str:
        return "Platform settings"

    @classmethod
    def get_settings(cls) -> "AdminSettings":
        """Return the single settings row; create with defaults if missing."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


def get_settings_for_vehicle_type(truck_type: str):
    """
    Return pricing/radius settings for the given vehicle type (e.g. 'Pickup', '12 Wheeler').
    If VehicleTypeSettings exists for that type, return it; else return global AdminSettings.
    """
    if not truck_type or not str(truck_type).strip():
        return AdminSettings.get_settings()
    from drivers.models import VehicleType
    name = str(truck_type).strip()
    try:
        vt = VehicleType.objects.get(name__iexact=name)
    except VehicleType.DoesNotExist:
        return AdminSettings.get_settings()
    try:
        return VehicleTypeSettings.objects.get(vehicle_type=vt)
    except VehicleTypeSettings.DoesNotExist:
        return AdminSettings.get_settings()


class PushNotification(models.Model):
    TARGET_ALL = "all"
    TARGET_DRIVERS = "drivers"
    TARGET_CUSTOMERS = "customers"
    TARGET_USER = "user"

    TARGET_CHOICES = [
        (TARGET_ALL, "All users"),
        (TARGET_DRIVERS, "All drivers"),
        (TARGET_CUSTOMERS, "All customers"),
        (TARGET_USER, "Individual user"),
    ]

    USER_TYPE_DRIVER = "driver"
    USER_TYPE_CUSTOMER = "customer"
    USER_TYPE_CHOICES = [
        (USER_TYPE_DRIVER, "Driver"),
        (USER_TYPE_CUSTOMER, "Customer"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_SENT = "sent"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SENT, "Sent"),
        (STATUS_FAILED, "Failed"),
    ]

    title = models.CharField(max_length=120)
    message = models.TextField()
    target = models.CharField(max_length=16, choices=TARGET_CHOICES, default=TARGET_ALL)

    # Only used when target="user"
    user_type = models.CharField(
        max_length=16, choices=USER_TYPE_CHOICES, blank=True, default=""
    )
    user_id = models.PositiveIntegerField(null=True, blank=True)

    # Notification type for app routing
    notification_type = models.CharField(
        max_length=32, blank=True, default="general_notification"
    )

    # Stored result for auditing/debugging
    send_result = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Push notification"
        verbose_name_plural = "Push notifications"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.title} ({self.target})"
