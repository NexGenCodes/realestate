from rest_framework import permissions
from users.models import User


class IsOwnerRole(permissions.BasePermission):
    """
    Allows access only to users with the OWNER or ADMIN role.
    """

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return request.user.role in [User.Role.OWNER, User.Role.ADMIN]


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Object-level permission to only allow owners of an object to edit it.
    Assumes the model instance has an `owner` attribute.
    """

    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request
        if request.method in permissions.SAFE_METHODS:
            return True

        # Check for 'owner' attribute directly (Property, etc.)
        # or 'property.owner' (TourRequest, Review, etc.)
        owner = getattr(obj, "owner", None)
        if owner is None and hasattr(obj, "property"):
            owner = getattr(obj.property, "owner", None)

        return (
            owner == request.user
            or request.user.is_staff
            or (hasattr(request.user, "role") and request.user.role == User.Role.ADMIN)
        )
