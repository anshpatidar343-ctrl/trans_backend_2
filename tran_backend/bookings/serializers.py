from decimal import Decimal

from rest_framework import serializers

from customers.models import Customer
from drivers.models import Driver

from .models import Booking
from core.services.distance import haversine_km
from core.models import get_settings_for_vehicle_type


class CreateBookingSerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    pickup_lat = serializers.FloatField()
    pickup_lng = serializers.FloatField()
    drop_lat = serializers.FloatField()
    drop_lng = serializers.FloatField()
    pickup_city = serializers.CharField(required=False, allow_blank=True, default="")
    drop_city = serializers.CharField(required=False, allow_blank=True, default="")
    truck_type = serializers.CharField()
    load_type = serializers.CharField(required=False, allow_blank=True, default="")
    booking_time = serializers.DateTimeField(required=False, allow_null=True)


class GetAvailableTrucksSerializer(serializers.Serializer):
    pickup_lat = serializers.FloatField()
    pickup_lng = serializers.FloatField()
    drop_lat = serializers.FloatField()
    drop_lng = serializers.FloatField()
    truck_type = serializers.CharField()
    booking_time = serializers.DateTimeField(required=False, allow_null=True)


class FareEstimateSerializer(serializers.Serializer):
    pickup_lat = serializers.FloatField()
    pickup_lng = serializers.FloatField()
    drop_lat = serializers.FloatField()
    drop_lng = serializers.FloatField()
    truck_type = serializers.CharField(required=False, allow_blank=True, default="")


class ConfirmBookingSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()


class AssignBookingSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    driver_id = serializers.IntegerField()


class VerifyOtpSerializer(serializers.Serializer):
    driver_id = serializers.IntegerField()
    booking_id = serializers.IntegerField()
    otp = serializers.CharField(min_length=4, max_length=4)


class SmartUnlockSerializer(serializers.Serializer):
    driver_id = serializers.IntegerField()
    booking_id = serializers.IntegerField()
    threshold_km = serializers.FloatField(required=False, default=25.0)


class BookingResponseSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    driver_id = serializers.SerializerMethodField()
    total_user_fare = serializers.SerializerMethodField()
    driver_fare_before_commission = serializers.SerializerMethodField()
    platform_charge = serializers.SerializerMethodField()
    platform_commission_percentage = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "user_id",
            "pickup_lat",
            "pickup_lng",
            "drop_lat",
            "drop_lng",
            "pickup_city",
            "drop_city",
            "booking_time",
            "truck_type",
            "load_type",
            "distance_km",
            "estimated_fare",
            "final_fare",
            "total_user_fare",
            "driver_fare_before_commission",
            "platform_charge",
            "platform_commission_percentage",
            "driver_id",
            "advance_amount",
            "payment_due_at",
            "payment_status",
            "pickup_otp",
            "booking_status",
        ]

    def get_user_id(self, obj):
        return obj.user_id

    def get_driver_id(self, obj):
        return obj.driver_id

    def _computed_fares(self, obj):
        # In this project, `estimated_fare/final_fare` are user-facing totals (driver fare + platform commission).
        total = Decimal(str(obj.final_fare or obj.estimated_fare or 0))
        total = total.quantize(Decimal("0.01"))

        settings = get_settings_for_vehicle_type(obj.truck_type or "")
        pct = Decimal(str(settings.platform_commission_percentage or 0)) / Decimal("100")
        if pct <= 0:
            return total, Decimal("0.00"), pct

        # total = driver_fare * (1 + pct)
        driver_fare = (total / (Decimal("1.00") + pct)).quantize(Decimal("0.01"))
        platform_charge = (total - driver_fare).quantize(Decimal("0.01"))
        return total, platform_charge, pct

    def get_platform_commission_percentage(self, obj):
        settings = get_settings_for_vehicle_type(obj.truck_type or "")
        return float(settings.platform_commission_percentage or 0)

    def get_total_user_fare(self, obj):
        total, _, _ = self._computed_fares(obj)
        return float(total)

    def get_driver_fare_before_commission(self, obj):
        total, platform_charge, _ = self._computed_fares(obj)
        driver_fare = (total - platform_charge).quantize(Decimal("0.01"))
        return float(driver_fare)

    def get_platform_charge(self, obj):
        _, platform_charge, _ = self._computed_fares(obj)
        return float(platform_charge)


class CustomerBookingSerializer(serializers.ModelSerializer):
    user_id = serializers.SerializerMethodField()
    driver_id = serializers.SerializerMethodField()
    driver_name = serializers.SerializerMethodField()
    driver_phone = serializers.SerializerMethodField()
    driver_vehicle_number = serializers.SerializerMethodField()
    driver_vehicle_type = serializers.SerializerMethodField()
    driver_current_lat = serializers.SerializerMethodField()
    driver_current_lng = serializers.SerializerMethodField()
    driver_distance_km = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "user_id",
            "pickup_lat",
            "pickup_lng",
            "drop_lat",
            "drop_lng",
            "pickup_city",
            "drop_city",
            "booking_time",
            "truck_type",
            "load_type",
            "distance_km",
            "estimated_fare",
            "final_fare",
            "driver_id",
            "driver_name",
            "driver_phone",
            "driver_vehicle_number",
            "driver_vehicle_type",
            "driver_current_lat",
            "driver_current_lng",
            "driver_distance_km",
            "pickup_otp",
            "booking_status",
            "advance_amount",
            "payment_due_at",
            "payment_status",
            "created_at",
            "updated_at",
        ]

    def get_user_id(self, obj):
        return obj.user_id

    def get_driver_id(self, obj):
        return obj.driver_id

    def _driver(self, obj):
        return getattr(obj, "driver", None)

    def get_driver_name(self, obj):
        d = self._driver(obj)
        return (d.full_name if d else "") or ""

    def get_driver_phone(self, obj):
        d = self._driver(obj)
        return (d.phone_number if d else "") or ""

    def get_driver_vehicle_number(self, obj):
        d = self._driver(obj)
        return (d.vehicle_number if d else "") or ""

    def get_driver_vehicle_type(self, obj):
        d = self._driver(obj)
        return (d.vehicle_type if d else "") or ""

    def get_driver_current_lat(self, obj):
        d = self._driver(obj)
        if not d or d.current_lat is None:
            return None
        return float(d.current_lat)

    def get_driver_current_lng(self, obj):
        d = self._driver(obj)
        if not d or d.current_lng is None:
            return None
        return float(d.current_lng)

    def get_driver_distance_km(self, obj):
        d = self._driver(obj)
        if not d or d.current_lat is None or d.current_lng is None:
            return None
        try:
            return float(
                haversine_km(float(d.current_lat), float(d.current_lng), float(obj.pickup_lat), float(obj.pickup_lng))
            )
        except Exception:
            return None


class DriverCardSerializer(serializers.Serializer):
    """For available trucks list: driver name, truck type, pickup distance, etc."""

    driver_id = serializers.IntegerField()
    driver_name = serializers.CharField()
    truck_type = serializers.CharField()
    truck_number = serializers.CharField()
    pickup_distance_km = serializers.FloatField()
    destination_distance_km = serializers.FloatField()
    available_time = serializers.DateTimeField(allow_null=True)
    estimated_fare = serializers.DecimalField(
        max_digits=12, decimal_places=2, allow_null=True
    )
    rating = serializers.FloatField(allow_null=True)


class CreatePaymentOrderSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()


class VerifyPaymentSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class CancelBookingSerializer(serializers.Serializer):
    booking_id = serializers.IntegerField()
    reason = serializers.CharField(required=False, allow_blank=True, default="")
