from rest_framework.permissions import BasePermission


class IsDriverAuthenticated(BasePermission):
    """
    Checks whether request.user is a Driver instance authenticated via JWT.
    """

    def has_permission(self, request, view) -> bool:
        user = getattr(request, "user", None)
        return user is not None and getattr(user, "id", None) is not None

