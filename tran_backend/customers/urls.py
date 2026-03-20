from django.urls import path

from . import views

urlpatterns = [
    path("signup/", views.customer_signup, name="customer-signup"),
    path("login/", views.customer_login, name="customer-login"),
    path("send-whatsapp-otp/", views.customer_send_whatsapp_otp, name="customer-send-whatsapp-otp"),
    path("verify-whatsapp-otp/", views.customer_verify_whatsapp_otp, name="customer-verify-whatsapp-otp"),
    path(
        "reset-password-with-whatsapp-otp/",
        views.customer_reset_password_with_whatsapp_otp,
        name="customer-reset-password-with-whatsapp-otp",
    ),
    path("status/<int:customer_id>/", views.customer_status, name="customer-status"),
    path(
        "<int:customer_id>/fcm-token/",
        views.set_customer_fcm_token,
        name="customer-fcm-token",
    ),
    path(
        "<int:customer_id>/fcm-token/clear/",
        views.clear_customer_fcm_token,
        name="customer-fcm-token-clear",
    ),
]
