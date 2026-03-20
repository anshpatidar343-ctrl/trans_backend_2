from django.urls import path

from . import views_user, views_driver

urlpatterns = [
    # User APIs
    path("online-vehicles/", views_user.online_vehicles),
    path("create-booking/", views_user.create_booking),
    path("get-available-trucks/", views_user.get_available_trucks),
    path("fare-estimate/", views_user.fare_estimate),
    path("confirm-booking/", views_user.confirm_booking),
    path("assign-booking/", views_user.assign_booking),
    path("create-payment-order/", views_user.create_payment_order),
    path("verify-payment/", views_user.verify_payment),
    path("cancel-booking/", views_user.cancel_booking),
    path("user-bookings/<int:user_id>/", views_user.user_bookings),
    path("payment-history/<int:user_id>/", views_user.payment_history),
    path("booking/<int:booking_id>/", views_user.booking_detail),
    path("booking-live/<int:booking_id>/", views_user.booking_live_location),
    # Driver APIs (booking-related)
    path("driver-online/", views_driver.driver_online),
    path("update-driver-location/", views_driver.update_driver_location),
    path("accept-booking/", views_driver.accept_booking),
    path("reject-booking/", views_driver.reject_booking),
    path("start-trip/", views_driver.start_trip),
    path("verify-otp/", views_driver.verify_otp),
    path("complete-trip/", views_driver.complete_trip),
    path("smart-unlock/", views_driver.smart_unlock),
    path("driver-bookings/<int:driver_id>/", views_driver.driver_bookings),
]
