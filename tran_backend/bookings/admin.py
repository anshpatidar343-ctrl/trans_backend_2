from decimal import Decimal

from django.contrib import admin

from core.models import get_settings_for_vehicle_type

from .models import Booking, Payment


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "user",
        "driver",
        "pickup_city",
        "drop_city",
        "truck_type",
        "distance_km",
        "final_fare",
        "booking_status",
        "payment_status",
        "advance_amount",
        "advance_paid_amount",
        "remaining_amount",
        "total_trip_fare",
        "driver_trip_fare",
        "platform_charge",
        "paid_at",
        "booking_time",
    )
    list_filter = (
        "booking_status",
        "payment_status",
        "truck_type",
        "driver",
        "user",
        "booking_time",
        "payment_due_at",
    )
    search_fields = (
        "user__full_name",
        "user__email",
        "driver__full_name",
        "pickup_city",
        "drop_city",
    )
    readonly_fields = (
        "booking_time",
        "created_at",
        "updated_at",
    )
    autocomplete_fields = ("user", "driver")

    def _total_trip_fare(self, obj: Booking) -> Decimal:
        # In this project `final_fare/estimated_fare` are user-facing totals (driver fare + platform commission).
        if obj.final_fare is not None:
            return Decimal(str(obj.final_fare)).quantize(Decimal("0.01"))
        if obj.estimated_fare is not None:
            return Decimal(str(obj.estimated_fare)).quantize(Decimal("0.01"))
        return Decimal("0.00")

    def _commission_breakdown(self, obj: Booking) -> tuple[Decimal, Decimal]:
        """
        Returns (platform_charge, driver_trip_fare) for this booking.
        """
        total_user_fare = self._total_trip_fare(obj)
        if total_user_fare <= 0:
            return Decimal("0.00"), Decimal("0.00")

        settings = get_settings_for_vehicle_type(obj.truck_type or "")
        commission_pct = Decimal(str(getattr(settings, "platform_commission_percentage", 0) or 0)) / Decimal("100")

        if commission_pct <= 0:
            return Decimal("0.00"), total_user_fare

        # total_user_fare = driver_fare * (1 + commission_pct)
        driver_fare = (total_user_fare / (Decimal("1.00") + commission_pct)).quantize(Decimal("0.01"))
        platform_charge = (total_user_fare - driver_fare).quantize(Decimal("0.01"))
        return platform_charge, driver_fare

    # --- columns for list_display ---
    def total_trip_fare(self, obj: Booking) -> str:
        return str(self._total_trip_fare(obj))

    def driver_trip_fare(self, obj: Booking) -> str:
        _, driver_fare = self._commission_breakdown(obj)
        return str(driver_fare)

    def platform_charge(self, obj: Booking) -> str:
        platform_charge, _ = self._commission_breakdown(obj)
        return str(platform_charge)

    def advance_paid_amount(self, obj: Booking) -> str:
        advance = Decimal(str(obj.advance_amount or 0)).quantize(Decimal("0.01"))
        if (obj.payment_status or "").lower() == "success":
            return str(advance)
        return "0.00"

    def remaining_amount(self, obj: Booking) -> str:
        # Remaining fare = total trip fare - advance amount (i.e., 90% balance).
        total = self._total_trip_fare(obj)
        advance = Decimal(str(obj.advance_amount or 0)).quantize(Decimal("0.01"))
        remaining = (total - advance).quantize(Decimal("0.01"))
        return str(max(remaining, Decimal("0.00")))

    def paid_at(self, obj: Booking):
        p = obj.payments.order_by("-created_at").first()
        return getattr(p, "created_at", None)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "booking",
        "status",
        "amount",
        "razorpay_order_id",
        "razorpay_payment_id",
        "created_at",
        "updated_at",
    )
    list_filter = ("status", "created_at", "updated_at", ("booking__driver"), ("booking__user"))
    search_fields = ("booking__id", "razorpay_payment_id", "razorpay_order_id")
    readonly_fields = (
        "razorpay_order_id",
        "razorpay_payment_id",
        "razorpay_signature",
        "amount",
        "status",
        "created_at",
        "updated_at",
        "booking",
    )
