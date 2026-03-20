from django.db import models


class VehicleType(models.Model):
    name = models.CharField(max_length=64, unique=True)
    icon = models.ImageField(upload_to="vehicle_icons/", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class Driver(models.Model):
    # Auth / identity
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, blank=True, default="")
    phone_number = models.CharField(max_length=20, unique=True)
    password = models.CharField(max_length=255)

    # Truck info (truck_type, truck_number, truck_capacity)
    vehicle_number = models.CharField(max_length=32, blank=True, default="")
    vehicle_type = models.CharField(max_length=32, blank=True, default="")
    truck_capacity = models.CharField(max_length=32, blank=True, default="")

    # Documents (uploaded by admin or driver app later)
    license_image = models.ImageField(upload_to="driver_docs/", null=True, blank=True)
    rc_book_image = models.ImageField(upload_to="driver_docs/", null=True, blank=True)
    permit_image = models.ImageField(upload_to="driver_docs/", null=True, blank=True)
    insurance_image = models.ImageField(upload_to="driver_docs/", null=True, blank=True)

    # Live location (updated every 10–15 sec)
    current_lat = models.FloatField(null=True, blank=True)
    current_lng = models.FloatField(null=True, blank=True)
    destination_lat = models.FloatField(null=True, blank=True)
    destination_lng = models.FloatField(null=True, blank=True)
    last_location_update = models.DateTimeField(null=True, blank=True)

    # Availability
    available_time = models.DateTimeField(null=True, blank=True)
    is_online = models.BooleanField(default=False)
    is_available = models.BooleanField(default=True)
    route_locked = models.BooleanField(default=False)

    # Reputation
    rating = models.FloatField(default=0.0, null=True, blank=True)

    # Push notifications
    # Token is per-device; if you want multi-device later, model it separately.
    fcm_token = models.CharField(max_length=255, blank=True, default="")
    fcm_token_updated_at = models.DateTimeField(null=True, blank=True)

    approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def name(self):
        return self.full_name

    @property
    def truck_type(self):
        return self.vehicle_type or ""

    @property
    def truck_number(self):
        return self.vehicle_number or ""

    def __str__(self) -> str:
        return f"{self.full_name} ({self.phone_number})"


class DriverLocation(models.Model):
    driver = models.OneToOneField(
        Driver, on_delete=models.CASCADE, related_name="location"
    )
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    is_online = models.BooleanField(default=False)
    current_city = models.CharField(max_length=128, blank=True, default="")
    current_area = models.CharField(max_length=128, blank=True, default="")
    destination = models.CharField(max_length=255, blank=True, default="")
    bid_amount = models.FloatField(null=True, blank=True, help_text="Driver's minimum bid for this route (₹)")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.driver.full_name} @ {self.latitude}, {self.longitude}"


class DriverRoute(models.Model):
    """
    Multiple operating routes per driver.
    A route can be:
    - destination-based (destination_lat/lng set)
    - free/anywhere (destination_lat/lng null)
    """

    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="routes")

    current_text = models.CharField(max_length=255, blank=True, default="")
    destination_text = models.CharField(max_length=255, blank=True, default="")

    destination_lat = models.FloatField(null=True, blank=True)
    destination_lng = models.FloatField(null=True, blank=True)

    available_from = models.DateTimeField(null=True, blank=True)
    bid_amount = models.FloatField(null=True, blank=True, help_text="Driver's minimum bid for this route (₹)")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        dest = self.destination_text or "Anywhere"
        return f"{self.driver.full_name}: {dest}"
