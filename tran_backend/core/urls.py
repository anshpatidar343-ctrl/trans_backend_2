from django.urls import path

from . import views_admin
from . import views_push

urlpatterns = [
    path("platform-settings/", views_admin.platform_settings),
    path("update-platform-settings/", views_admin.update_platform_settings),
    path("booking-analytics/", views_admin.booking_analytics),
    path("driver-analytics/", views_admin.driver_analytics),
    path("push/send/", views_push.send_push),
]
