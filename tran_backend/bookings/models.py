from django.db import models
from django.utils import timezone

from customers.models import Customer
from drivers.models import Driver


class Booking(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ACCEPTED = "accepted"
    STATUS_DRIVER_ASSIGNED = "driver_assigned"
    STATUS_STARTED = "started"
    STATUS_IN_TRANSIT = "in_transit"
    STATUS_COMPLETED = "completed"
    STATUS_CANCELLED = "cancelled"
    STATUS_AWAITING_PAYMENT = "awaiting_payment"

    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_AWAITING_PAYMENT, "Awaiting payment"),
        (STATUS_DRIVER_ASSIGNED, "Driver assigned"),
        (STATUS_STARTED, "Started"),
        (STATUS_IN_TRANSIT, "In transit"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    user = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="bookings",
    )
    pickup_lat = models.FloatField()
    pickup_lng = models.FloatField()
    drop_lat = models.FloatField()
    drop_lng = models.FloatField()
    pickup_city = models.CharField(max_length=128, blank=True, default="")
    drop_city = models.CharField(max_length=128, blank=True, default="")

    booking_time = models.DateTimeField(auto_now_add=True)
    truck_type = models.CharField(max_length=64)
    load_type = models.CharField(max_length=128, blank=True, default="")
    distance_km = models.FloatField(default=0.0)
    estimated_fare = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, null=True, blank=True
    )
    final_fare = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    driver = models.ForeignKey(
        Driver,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="bookings",
    )
    booking_status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_PENDING
    )

    # Matching/search (Option A worker)
    search_started_at = models.DateTimeField(null=True, blank=True)
    search_expires_at = models.DateTimeField(null=True, blank=True)
    last_batch_sent_at = models.DateTimeField(null=True, blank=True)

    # Payment flow
    advance_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    payment_due_at = models.DateTimeField(null=True, blank=True)
    payment_status = models.CharField(
        max_length=16,
        blank=True,
        default="",
        help_text="pending|success|failed",
    )

    # OTP: generated per booking, verified at pickup to start trip
    pickup_otp = models.CharField(max_length=4, blank=True, default="")
    otp_verified_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Booking #{self.id} ({self.booking_status})"

    def is_payment_expired(self) -> bool:
        if not self.payment_due_at:
            return False
        return timezone.now() > self.payment_due_at


class Payment(models.Model):
    STATUS_PENDING = "pending"
    STATUS_SUCCESS = "success"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILED, "Failed"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="payments")

    razorpay_order_id = models.CharField(max_length=64, blank=True, default="")
    razorpay_payment_id = models.CharField(max_length=64, blank=True, default="")
    razorpay_signature = models.CharField(max_length=128, blank=True, default="")

    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Payment #{self.id} ({self.status}) for Booking #{self.booking_id}"


class BookingDriverRequest(models.Model):
    STATUS_SENT = "sent"
    STATUS_ACCEPTED = "accepted"
    STATUS_REJECTED = "rejected"
    STATUS_EXPIRED = "expired"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_SENT, "Sent"),
        (STATUS_ACCEPTED, "Accepted"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_EXPIRED, "Expired"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name="driver_requests")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, related_name="booking_requests")
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_SENT)

    sent_at = models.DateTimeField(auto_now_add=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("booking", "driver")
        indexes = [
            models.Index(fields=["booking", "status"]),
            models.Index(fields=["driver", "status"]),
        ]

    def __str__(self) -> str:
        return f"Booking #{self.booking_id} -> Driver #{self.driver_id} ({self.status})"
