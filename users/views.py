import logging
from django.db import transaction
from rest_framework import generics, viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.contrib.auth import get_user_model
from shared.messaging import (
    notify_admin_new_owner_request,
    check_email_credits,
    notify_user_owner_request_status,
)
from drf_yasg.utils import swagger_auto_schema
from .serializers import (
    UserSerializer,
    OwnerRequestSerializer,
    AdminOwnerRequestSerializer,
    SavedSearchSerializer,
    DeviceTokenSerializer,
    NotificationSerializer,
)
from .models import OwnerRequest, SavedSearch, DeviceToken, Notification
from shared.security import BurstRateThrottle
from .services import OwnerRequestService, NotificationService

logger = logging.getLogger(__name__)

User = get_user_model()


class ProfileView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

    def get_throttles(self):
        if self.request.method in ["PUT", "PATCH"]:
            return [BurstRateThrottle()]
        return super().get_throttles()

    @swagger_auto_schema(
        operation_summary="Get/Update User Profile",
        operation_description="Retrieve or update the authenticated user's profile information.",
        tags=["User Profile"],
    )
    def patch(self, request, *args, **kwargs):
        return super().patch(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Update User Profile (Full)",
        operation_description="Perform a full update of the user's profile.",
        tags=["User Profile"],
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Get User Profile",
        operation_description="Retrieve the authenticated user's profile.",
        tags=["User Profile"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @transaction.atomic
    def perform_update(self, serializer):
        user = self.request.user
        logger.info(f"[PROFILE] User {user.email} is updating their profile.")
        serializer.save()
        logger.info(f"[PROFILE] Profile update successful for user {user.email}")


class OwnerRequestView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OwnerRequestSerializer
    throttle_classes = [BurstRateThrottle]

    @swagger_auto_schema(
        operation_summary="List/Create Owner Requests",
        operation_description="List current owner requests or submit a new one for the authenticated user.",
        tags=["Owner Requests"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Submit Owner Request",
        operation_description="Submit a new request to become a property owner. Requires ID document upload and reason.",
        tags=["Owner Requests"],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        return OwnerRequest.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        instance = OwnerRequestService.create_request(
            self.request.user, serializer.validated_data
        )
        serializer.instance = instance


class AdminOwnerRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = OwnerRequest.objects.all()
    serializer_class = AdminOwnerRequestSerializer
    http_method_names = ["get", "put", "patch", "head", "options"]

    @swagger_auto_schema(
        operation_summary="Manage Owner Requests (Admin)",
        operation_description="Admin interface to view, approve, or reject owner requests.",
        tags=["Admin Operations"],
    )
    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        OwnerRequestService.process_request(instance, self.request.user)


@swagger_auto_schema(
    operation_summary="Manage Users (Admin)",
    operation_description="Admin interface to manage all users in the system.",
    tags=["Admin Operations"],
)
class AdminUserViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = User.objects.all()
    serializer_class = UserSerializer


class SavedSearchViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user's saved searches."""

    serializer_class = SavedSearchSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        if (
            getattr(self, "swagger_fake_view", False)
            or not self.request.user.is_authenticated
        ):
            return SavedSearch.objects.none()
        return SavedSearch.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        logger.info(f"User {self.request.user.email} saved a new search.")


class DeviceTokenViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user device tokens for push notifications."""

    serializer_class = DeviceTokenSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return DeviceToken.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for managing user notifications."""

    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def mark_as_read(self, request, pk=None):
        notification = self.get_object()
        try:
            NotificationService.mark_as_read(notification, request.user)
            return Response({"status": "notification marked as read"})
        except PermissionError as e:
            return Response({"error": str(e)}, status=status.HTTP_403_FORBIDDEN)

    @action(detail=False, methods=["post"])
    def mark_all_as_read(self, request):
        """Mark all unread notifications for the current user as read."""
        updated_count = NotificationService.mark_all_as_read(request.user)
        return Response(
            {"status": f"{updated_count} notifications marked as read"},
            status=status.HTTP_200_OK,
        )
