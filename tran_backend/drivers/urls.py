from django.urls import path

from . import views

urlpatterns = [
    path("signup/", views.driver_signup, name="driver-signup"),
    path("login/", views.driver_login, name="driver-login"),
    path("send-whatsapp-otp/", views.driver_send_whatsapp_otp, name="driver-send-whatsapp-otp"),
    path("verify-whatsapp-otp/", views.driver_verify_whatsapp_otp, name="driver-verify-whatsapp-otp"),
    path(
        "reset-password-with-whatsapp-otp/",
        views.driver_reset_password_with_whatsapp_otp,
        name="driver-reset-password-with-whatsapp-otp",
    ),
    path("vehicle-types/", views.vehicle_types, name="vehicle-types"),
    path("status/<int:driver_id>/", views.driver_status, name="driver-status"),
    path(
        "location/<int:driver_id>/",
        views.update_location,
        name="driver-update-location",
    ),
    path(
        "<int:driver_id>/routes/",
        views.driver_routes,
        name="driver-routes",
    ),
    path(
        "<int:driver_id>/routes/<int:route_id>/",
        views.delete_driver_route,
        name="driver-route-delete",
    ),
    path(
        "<int:driver_id>/profile/",
        views.driver_profile,
        name="driver-profile",
    ),
    path(
        "<int:driver_id>/fcm-token/",
        views.set_driver_fcm_token,
        name="driver-fcm-token",
    ),
    path(
        "<int:driver_id>/fcm-token/clear/",
        views.clear_driver_fcm_token,
        name="driver-fcm-token-clear",
    ),
]

