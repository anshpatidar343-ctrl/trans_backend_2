import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.services.matching import MatchingService
from core.services.fcm import send_data_multicast, send_notification
from drivers.models import Driver

from bookings.models import Booking, BookingDriverRequest


class Command(BaseCommand):
    help = "Background matching worker: dispatch booking_request in batches until accepted/timeout."

    def add_arguments(self, parser):
        parser.add_argument("--sleep", type=float, default=3.0, help="Loop sleep in seconds.")
        parser.add_argument("--batch", type=int, default=3, help="Drivers per batch.")
        parser.add_argument(
            "--response-window",
            type=int,
            default=30,
            help="Seconds to wait for a batch response before sending next batch.",
        )
        parser.add_argument(
            "--max-seconds",
            type=int,
            default=120,
            help="Max seconds to search before cancelling (if booking.search_expires_at not set).",
        )

    def handle(self, *args, **opts):
        sleep_s: float = float(opts["sleep"])
        batch_size: int = int(opts["batch"])
        response_window_s: int = int(opts["response_window"])
        max_seconds: int = int(opts["max_seconds"])

        self.stdout.write(self.style.SUCCESS("Matching worker started."))
        while True:
            try:
                self._tick(batch_size=batch_size, response_window_s=response_window_s, max_seconds=max_seconds)
            except Exception as e:
                self.stderr.write(f"[matching_worker] error: {e}")
            time.sleep(sleep_s)

    def _tick(self, *, batch_size: int, response_window_s: int, max_seconds: int):
        now = timezone.now()
        pending = (
            Booking.objects.filter(booking_status=Booking.STATUS_PENDING)
            .select_related("user")
            .order_by("created_at")[:50]
        )

        for booking in pending:
            # Skip if already assigned
            if booking.driver_id is not None:
                continue

            # Ensure search window fields
            if booking.search_started_at is None:
                booking.search_started_at = now
            if booking.search_expires_at is None:
                booking.search_expires_at = booking.search_started_at + timedelta(seconds=max_seconds)

            if booking.search_expires_at and now > booking.search_expires_at:
                self._cancel_no_driver(booking)
                continue

            # If we recently sent a batch, wait for response window
            if booking.last_batch_sent_at and now < booking.last_batch_sent_at + timedelta(seconds=response_window_s):
                continue

            # Expire any still-sent requests from old batches
            BookingDriverRequest.objects.filter(
                booking=booking,
                status=BookingDriverRequest.STATUS_SENT,
                sent_at__lt=now - timedelta(seconds=response_window_s),
            ).update(status=BookingDriverRequest.STATUS_EXPIRED)

            # Send next batch
            self._dispatch_next_batch(booking, batch_size=batch_size, response_window_s=response_window_s)

    def _dispatch_next_batch(
        self,
        booking: Booking,
        *,
        batch_size: int,
        response_window_s: int,
    ):
        # Drivers already attempted for this booking
        attempted_ids = set(
            BookingDriverRequest.objects.filter(booking=booking).values_list("driver_id", flat=True)
        )

        drivers_qs = (
            Driver.objects.filter(is_online=True, is_available=True, route_locked=False)
            .select_related("location")
            .prefetch_related("routes")
        )

        # Progressive pickup radius expansion:
        # Every ~response-window seconds we expand the effective pickup radius so the
        # customer experiences "range increasing" until a driver accepts.
        #
        # NOTE: create-booking dispatches the first batch immediately (multiplier=1.0).
        # The worker sends the next batch after response-window seconds, so "step=1"
        # lines up with your 30-second timer.
        search_started_at = getattr(booking, "search_started_at", None) or timezone.now()
        elapsed_s = max(0.0, (timezone.now() - search_started_at).total_seconds())
        step = int(elapsed_s // float(response_window_s))

        # Increase multiplier each step; capped to avoid runaway matching.
        RADIUS_MULTIPLIER_PER_STEP = 0.25
        MAX_RADIUS_MULTIPLIER = 2.0
        pickup_radius_multiplier = min(1.0 + (step * RADIUS_MULTIPLIER_PER_STEP), MAX_RADIUS_MULTIPLIER)

        matches = MatchingService.filter_and_sort_drivers(
            drivers_qs,
            booking.pickup_lat,
            booking.pickup_lng,
            booking.drop_lat,
            booking.drop_lng,
            booking.truck_type,
            booking.booking_time,
            pickup_radius_multiplier=pickup_radius_multiplier,
        )

        next_drivers = []
        for d, _, _ in matches:
            if d.id in attempted_ids:
                continue
            next_drivers.append(d)
            if len(next_drivers) >= batch_size:
                break

        if not next_drivers:
            # No more drivers to try
            self._cancel_no_driver(booking)
            return

        tokens = []
        for d in next_drivers:
            BookingDriverRequest.objects.get_or_create(
                booking=booking,
                driver=d,
                defaults={"status": BookingDriverRequest.STATUS_SENT},
            )
            tk = (getattr(d, "fcm_token", "") or "").strip()
            if tk:
                tokens.append(tk)

        booking.last_batch_sent_at = timezone.now()
        booking.save(update_fields=["search_started_at", "search_expires_at", "last_batch_sent_at", "updated_at"])

        if not tokens:
            return

        send_data_multicast(
            tokens=tokens,
            data={
                "type": "NEW_BOOKING",
                "booking_id": str(booking.id),
                "pickup_lat": str(booking.pickup_lat),
                "pickup_lng": str(booking.pickup_lng),
                "drop_lat": str(booking.drop_lat),
                "drop_lng": str(booking.drop_lng),
                "truck_type": booking.truck_type or "",
                "pickup_city": booking.pickup_city or "",
                "drop_city": booking.drop_city or "",
                "load_type": booking.load_type or "",
                "distance_km": str(booking.distance_km or 0.0),
                "estimated_fare": str(booking.estimated_fare or ""),
            },
            android_channel_id="booking_alerts_v2",
        )

    def _cancel_no_driver(self, booking: Booking):
        # Idempotent-ish: if already cancelled, skip
        if booking.booking_status == Booking.STATUS_CANCELLED:
            return

        with transaction.atomic():
            b = Booking.objects.select_for_update().select_related("user").get(pk=booking.id)
            if b.booking_status != Booking.STATUS_PENDING:
                return
            b.booking_status = Booking.STATUS_CANCELLED
            b.save(update_fields=["booking_status", "updated_at"])

        # Notify customer (best effort)
        try:
            token = (getattr(booking.user, "fcm_token", "") or "").strip()
            if token:
                send_notification(
                    token=token,
                    title="No drivers available",
                    body="Please try again in a moment.",
                    data={"type": "booking_cancel", "booking_id": str(booking.id), "reason": "no_driver_available"},
                    android_channel_id="general",
                )
        except Exception:
            pass

