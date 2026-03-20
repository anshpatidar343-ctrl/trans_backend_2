from django.contrib.auth.hashers import make_password
from rest_framework import serializers

from .models import Driver, DriverLocation, DriverRoute, VehicleType


class DriverSignupSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = [
            "id",
            "full_name",
            "email",
            "phone_number",
            "password",
            "vehicle_number",
            "vehicle_type",
            "truck_capacity",
            "license_image",
            "rc_book_image",
            "permit_image",
            "insurance_image",
            "approved",
            "created_at",
        ]
        read_only_fields = ["id", "approved", "created_at"]
        extra_kwargs = {"password": {"write_only": True}}

    def validate_password(self, value: str) -> str:
        return make_password(value)


class DriverLoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField()
    password = serializers.CharField()


class VehicleTypeSerializer(serializers.ModelSerializer):
    icon_url = serializers.SerializerMethodField()

    class Meta:
        model = VehicleType
        fields = ["id", "name", "icon_url"]

    def get_icon_url(self, obj):
        request = self.context.get("request")
        if not getattr(obj, "icon", None):
            return ""
        try:
            url = obj.icon.url
        except Exception:
            return ""
        if request is None:
            return url
        return request.build_absolute_uri(url)


class DriverLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverLocation
        fields = [
            "driver",
            "latitude",
            "longitude",
            "is_online",
            "current_city",
            "current_area",
            "destination",
            "bid_amount",
            "updated_at",
        ]


class DriverRouteSerializer(serializers.ModelSerializer):
    class Meta:
        model = DriverRoute
        fields = [
            "id",
            "driver",
            "current_text",
            "destination_text",
            "destination_lat",
            "destination_lng",
            "available_from",
            "bid_amount",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class DriverUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Driver
        fields = [
            "full_name",
            "email",
            "phone_number",
            "vehicle_number",
            "vehicle_type",
            "truck_capacity",
            "license_image",
            "rc_book_image",
            "permit_image",
            "insurance_image",
        ]


class DriverProfileSerializer(serializers.ModelSerializer):
    location = serializers.SerializerMethodField()
    active_routes = serializers.SerializerMethodField()
    vehicle_icon_url = serializers.SerializerMethodField()
    documents = serializers.SerializerMethodField()

    class Meta:
        model = Driver
        fields = [
            "id",
            "full_name",
            "email",
            "phone_number",
            "vehicle_number",
            "vehicle_type",
            "truck_capacity",
            "rating",
            "approved",
            "is_online",
            "available_time",
            "current_lat",
            "current_lng",
            "location",
            "active_routes",
            "vehicle_icon_url",
            "documents",
        ]

    def get_location(self, obj):
        loc = getattr(obj, "location", None)
        if not loc:
            return None
        return DriverLocationSerializer(loc).data

    def get_active_routes(self, obj):
        qs = obj.routes.filter(is_active=True).order_by("-updated_at")
        return DriverRouteSerializer(qs, many=True).data

    def get_vehicle_icon_url(self, obj):
        name = (obj.vehicle_type or "").strip()
        if not name:
            return ""
        vt = VehicleType.objects.filter(name__iexact=name).first()
        if not vt or not getattr(vt, "icon", None):
            return ""
        try:
            url = vt.icon.url
        except Exception:
            return ""
        request = self.context.get("request")
        if request is None:
            return url
        return request.build_absolute_uri(url)

    def get_documents(self, obj):
        request = self.context.get("request")

        def _url(field_name: str) -> str:
            f = getattr(obj, field_name, None)
            if not f:
                return ""
            try:
                u = f.url
            except Exception:
                return ""
            if request is None:
                return u
            return request.build_absolute_uri(u)

        return {
            "license_image_url": _url("license_image"),
            "rc_book_image_url": _url("rc_book_image"),
            "permit_image_url": _url("permit_image"),
            "insurance_image_url": _url("insurance_image"),
        }
