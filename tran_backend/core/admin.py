from django import forms
from django.contrib import admin
from django.utils import timezone

from customers.models import Customer
from drivers.models import Driver

from core.services.fcm import send_multicast, send_notification
from .models import AdminSettings, PushNotification, VehicleTypeSettings


@admin.register(VehicleTypeSettings)
class VehicleTypeSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "vehicle_type",
        "short_distance_limit_km",
        "pickup_radius_km",
        "destination_radius_km",
        "base_fare_short_distance",
        "per_km_rate_short_distance",
        "per_km_rate_long_distance",
        "platform_commission_percentage",
        "surge_multiplier",
        "updated_at",
    )
    list_filter = ("vehicle_type",)
    search_fields = ("vehicle_type__name",)
    fieldsets = (
        (
            "Vehicle type",
            {"fields": ("vehicle_type",)},
        ),
        (
            "Distance limits (km)",
            {
                "fields": (
                    "short_distance_limit_km",
                    "long_distance_limit_km",
                    "pickup_radius_km",
                    "destination_radius_km",
                )
            },
        ),
        (
            "Short distance pricing",
            {
                "fields": (
                    "base_fare_short_distance",
                    "per_km_rate_short_distance",
                )
            },
        ),
        (
            "Long distance pricing",
            {"fields": ("per_km_rate_long_distance",)},
        ),
        (
            "Commission & surge",
            {
                "fields": (
                    "platform_commission_percentage",
                    "surge_multiplier",
                )
            },
        ),
    )


@admin.register(AdminSettings)
class AdminSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "short_distance_limit_km",
        "pickup_radius_km",
        "destination_radius_km",
        "platform_commission_percentage",
        "surge_multiplier",
        "enable_driver_bidding",
        "updated_at",
    )
    fieldsets = (
        (
            "Distance limits (km)",
            {
                "fields": (
                    "short_distance_limit_km",
                    "long_distance_limit_km",
                    "pickup_radius_km",
                    "destination_radius_km",
                )
            },
        ),
        (
            "Short distance pricing",
            {
                "fields": (
                    "base_fare_short_distance",
                    "per_km_rate_short_distance",
                )
            },
        ),
        (
            "Long distance pricing",
            {"fields": ("per_km_rate_long_distance",)},
        ),
        (
            "Commission & surge",
            {
                "fields": (
                    "platform_commission_percentage",
                    "surge_multiplier",
                )
            },
        ),
        (
            "Operational",
            {
                "fields": (
                    "driver_location_update_interval",
                    "enable_driver_bidding",
                )
            },
        ),
    )

    def has_add_permission(self, request):
        return not AdminSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


class PushNotificationAdminForm(forms.ModelForm):
    driver = forms.ModelChoiceField(
        queryset=Driver.objects.all().order_by("-id"),
        required=False,
        help_text="Select a driver when Target = Individual user and User type = Driver.",
    )
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.all().order_by("-id"),
        required=False,
        help_text="Select a customer when Target = Individual user and User type = Customer.",
    )

    class Meta:
        model = PushNotification
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        inst: PushNotification | None = kwargs.get("instance")

        # Pre-fill dropdowns from stored user_id/user_type
        if inst and inst.user_id and inst.user_type:
            try:
                if inst.user_type == PushNotification.USER_TYPE_DRIVER:
                    self.fields["driver"].initial = Driver.objects.filter(pk=int(inst.user_id)).first()
                elif inst.user_type == PushNotification.USER_TYPE_CUSTOMER:
                    self.fields["customer"].initial = Customer.objects.filter(pk=int(inst.user_id)).first()
            except Exception:
                pass

    def clean(self):
        cleaned = super().clean()
        target = (cleaned.get("target") or "").strip()
        user_type = (cleaned.get("user_type") or "").strip()

        if target != PushNotification.TARGET_USER:
            cleaned["user_type"] = ""
            cleaned["user_id"] = None
            cleaned["driver"] = None
            cleaned["customer"] = None
            return cleaned

        if user_type == PushNotification.USER_TYPE_DRIVER:
            d = cleaned.get("driver")
            if d is None:
                raise forms.ValidationError("Please select a Driver.")
            cleaned["user_id"] = int(d.id)
            cleaned["customer"] = None
        elif user_type == PushNotification.USER_TYPE_CUSTOMER:
            c = cleaned.get("customer")
            if c is None:
                raise forms.ValidationError("Please select a Customer.")
            cleaned["user_id"] = int(c.id)
            cleaned["driver"] = None
        else:
            raise forms.ValidationError("Please select User type (Driver/Customer).")

        return cleaned


class PushNotificationAdmin(admin.ModelAdmin):
    form = PushNotificationAdminForm
    list_display = ("id", "title", "target", "notification_type", "status", "created_at", "sent_at")
    list_filter = ("target", "status", "notification_type", "created_at")
    search_fields = ("title", "message")
    readonly_fields = ("user_id", "status", "send_result", "error_message", "sent_at", "created_at")

    fieldsets = (
        ("Message", {"fields": ("title", "message", "notification_type")}),
        ("Target", {"fields": ("target", "user_type", "driver", "customer", "user_id")}),
        ("Delivery", {"fields": ("status", "sent_at", "send_result", "error_message", "created_at")}),
    )

    def save_model(self, request, obj, form, change):
        """
        On Save: send push once (draft -> sent/failed).
        If you want to re-send, create a new row (keeps audit trail).
        """
        if not change:
            obj.status = PushNotification.STATUS_DRAFT
        super().save_model(request, obj, form, change)

        if obj.status != PushNotification.STATUS_DRAFT:
            return

        try:
            data = {"type": obj.notification_type or "general_notification"}

            if obj.target == PushNotification.TARGET_USER:
                if obj.user_type == PushNotification.USER_TYPE_DRIVER:
                    u = Driver.objects.filter(pk=int(obj.user_id or 0)).first()
                else:
                    u = Customer.objects.filter(pk=int(obj.user_id or 0)).first()
                if u is None:
                    raise ValueError("User not found.")
                token = (getattr(u, "fcm_token", "") or "").strip()
                if not token:
                    raise ValueError("User has no fcm_token.")
                msg_id = send_notification(
                    token=token,
                    title=obj.title,
                    body=obj.message,
                    data=data,
                    android_channel_id="general",
                )
                obj.send_result = {"message_id": msg_id}
            else:
                if obj.target == PushNotification.TARGET_DRIVERS:
                    tokens = list(Driver.objects.exclude(fcm_token="").values_list("fcm_token", flat=True))
                elif obj.target == PushNotification.TARGET_CUSTOMERS:
                    tokens = list(Customer.objects.exclude(fcm_token="").values_list("fcm_token", flat=True))
                else:
                    tokens = list(Driver.objects.exclude(fcm_token="").values_list("fcm_token", flat=True)) + list(
                        Customer.objects.exclude(fcm_token="").values_list("fcm_token", flat=True)
                    )

                obj.send_result = send_multicast(
                    tokens=tokens,
                    title=obj.title,
                    body=obj.message,
                    data=data,
                    android_channel_id="general",
                )

            obj.status = PushNotification.STATUS_SENT
            obj.sent_at = timezone.now()
            obj.error_message = ""
        except Exception as e:
            obj.status = PushNotification.STATUS_FAILED
            obj.error_message = str(e)
        obj.save(update_fields=["status", "sent_at", "send_result", "error_message"])


admin.site.register(PushNotification, PushNotificationAdmin)
