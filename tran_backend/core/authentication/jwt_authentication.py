from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.request import Request

from drivers.models import Driver
from core.services.jwt_service import decode_driver_access_token


class JWTAuthentication(BaseAuthentication):
    """
    Expects: Authorization: Bearer <token>
    Sets request.user to the authenticated Driver instance.
    """

    def authenticate(self, request: Request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        token = parts[1].strip()
        if not token:
            return None

        try:
            payload = decode_driver_access_token(token)
        except Exception as e:
            raise AuthenticationFailed(str(e))

        driver_id_raw = payload.get("sub")
        if driver_id_raw is None:
            raise AuthenticationFailed("Token missing sub.")

        try:
            driver_id = int(driver_id_raw)
        except Exception:
            raise AuthenticationFailed("Invalid driver id in token.")

        try:
            driver = Driver.objects.get(pk=driver_id)
        except Driver.DoesNotExist:
            raise AuthenticationFailed("Driver not found.")

        # DRF will store it in request.user.
        return (driver, payload)

