import logging
from django.db import transaction
from rest_framework import generics, viewsets, permissions
from django.contrib.auth import get_user_model
from shared.messaging import (
    send_owner_approval_email,
    notify_admin_new_owner_request,
    check_email_credits,
)
from drf_yasg.utils import swagger_auto_schema
from .serializers import (
    UserSerializer,
    OwnerRequestSerializer,
    AdminOwnerRequestSerializer,
)
from .models import OwnerRequest

logger = logging.getLogger(__name__)

User = get_user_model()


class ProfileView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        return self.request.user

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
        logger.info(f"User {user.username} is updating their profile.")
        serializer.save()
        logger.info(f"Profile update successful for user {user.username}")


class OwnerRequestView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OwnerRequestSerializer

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
        instance = serializer.save(user=self.request.user)
        logger.info(f"Owner request {instance.id} created with status PENDING.")

        check_email_credits()

        # Notify admin of new owner request
        notify_admin_new_owner_request(
            user_name=f"{instance.user.first_name} {instance.user.last_name}",
            user_email=instance.user.email,
            id_type=instance.get_id_type_display(),
            reason=instance.reason,
        )


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
        if instance.status == OwnerRequest.Status.APPROVED:
            instance.user.role = User.Role.OWNER
            instance.user.save()
            instance.is_verified = True
            instance.save()
            # Email can be async as it's not blocking the critical flow for the admin
            try:
                send_owner_approval_email(instance.user.email, instance.user.first_name)
                logger.info(
                    f"Admin approved OwnerRequest {instance.id} for user {instance.user.username}. Approval email triggered."
                )
            except Exception as e:
                logger.error(
                    f"Failed to trigger approval email for {instance.user.email}: {str(e)}"
                )


@swagger_auto_schema(
    operation_summary="Manage Users (Admin)",
    operation_description="Admin interface to manage all users in the system.",
    tags=["Admin Operations"],
)
class AdminUserViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = User.objects.all()
    serializer_class = UserSerializer
