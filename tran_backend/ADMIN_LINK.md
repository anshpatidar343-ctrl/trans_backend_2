# One Admin Panel (Driver app + Customer app)

**URL (local):** [http://10.86.133.150:8000/admin/](http://10.86.133.150:8000/admin/)

This single admin panel lets you manage **both** the Driver app and the Customer app.

## First-time login

Create a superuser (if you haven’t already):

```bash
cd C:\tran_backend
.\venv\Scripts\activate
python manage.py createsuperuser
```

Enter username, email, and password when prompted, then log in at the link above.

## What you manage from one place

| Section      | Models              | Used by    |
|-------------|---------------------|------------|
| **Driver app**  | Drivers, Vehicle types, Driver locations | Driver app |
| **Customer app**| Customers           | Customer app |

- **Driver app:** Drivers, Vehicle types, Driver locations (view/edit from one screen; location can be edited inline on a driver).
- **Customer app:** Customers (accounts created from the customer app).
