# Logistics / Truck Booking Platform – API Reference

Base URL (local): `http://10.86.133.150:8000/api/`

---

## User APIs (Customer app)

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/fare-estimate/?pickup_lat=&pickup_lng=&drop_lat=&drop_lng=` | Distance and fare estimate (uses admin pricing + commission) |
| POST | `/get-available-trucks/` | List drivers matching pickup/drop and truck type (admin radius) |
| POST | `/create-booking/` | Create booking (user_id, pickup/drop coords, truck_type) |
| POST | `/confirm-booking/` | Confirm booking (booking_id) |

### Request bodies

**get-available-trucks:**  
`{ "pickup_lat", "pickup_lng", "drop_lat", "drop_lng", "truck_type" }`

**create-booking:**  
`{ "user_id", "pickup_lat", "pickup_lng", "drop_lat", "drop_lng", "truck_type", "pickup_city?", "drop_city?" }`

**confirm-booking:**  
`{ "booking_id" }`

---

## Driver APIs (Driver app)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/driver-online/` | Set is_online, available_time, destination (driver_id required) |
| POST | `/update-driver-location/` | Update current_lat, current_lng (every 10–15 sec) |
| POST | `/accept-booking/` | Accept a pending booking (driver_id, booking_id) |
| POST | `/reject-booking/` | Reject an assigned booking (driver_id, booking_id) |

### Request bodies

**driver-online:**  
`{ "driver_id", "is_online", "available_time?" (ISO), "destination_lat?", "destination_lng?" }`

**update-driver-location:**  
`{ "driver_id", "current_lat", "current_lng" }`

**accept-booking / reject-booking:**  
`{ "driver_id", "booking_id" }`

---

## Admin APIs

Base: `http://10.86.133.150:8000/api/admin/`

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/platform-settings/` | Get current AdminSettings (read-only) |
| POST | `/update-platform-settings/` | Update any settings (pickup_radius_km, commission, etc.) |
| GET | `/booking-analytics/` | Booking counts by status, revenue, platform commission |
| GET | `/driver-analytics/` | Total / online / approved driver counts |

---

## Admin panel (Django)

**URL:** http://10.86.133.150:8000/admin/

- **Platform configuration:** Single row for AdminSettings (pickup/destination radius, short/long distance pricing, commission, surge, driver update interval, driver bidding).
- **Driver app:** Drivers (with location, availability, rating), Vehicle types, Driver locations.
- **Customer app:** Customers.
- **Bookings:** All bookings with status, fare, driver.

---

## Fare logic (admin-configured)

- **Short distance** (distance ≤ `short_distance_limit_km`):  
  `fare = base_fare_short_distance + (distance × per_km_rate_short_distance)`
- **Long distance:**  
  `fare = distance × per_km_rate_long_distance`
- **Commission:** `total_user_price = driver_fare + (driver_fare × platform_commission_percentage / 100)`

---

## Matching logic (admin-configured)

1. Load AdminSettings.
2. Filter drivers: `is_online=True`, `truck_type` matches booking.
3. Pickup distance = Haversine(driver current, user pickup). Must be ≤ `pickup_radius_km`.
4. Destination distance = Haversine(driver destination, user drop). Must be ≤ `destination_radius_km`.
5. Driver `available_time` must be ≤ booking time (driver free by then).
6. Sort by pickup distance (nearest first).

---

## PostgreSQL

In `.env`:

```env
DB_ENGINE=django.db.backends.postgresql
DB_NAME=your_db_name
DB_USER=your_user
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
```

Install: `pip install psycopg2-binary`

---

## Scaling (100k+ drivers)

- **PostGIS:** Use `django.contrib.gis` and GeoQuerySet for radius filters.
- **Redis:** Cache driver locations; update from `update-driver-location`; use in matching.
- **WebSockets:** Notify drivers of new bookings and users of status in real time.
- **Celery:** Use for fare calculation, matching, and analytics in background tasks.
