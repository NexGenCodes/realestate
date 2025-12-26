import logging
from django.db import transaction
from rest_framework import status, generics, viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from shared.cache_utils import set_key, get_key, delete_key
from shared.otp_utils import generate_otp
from shared.messaging import (
    send_owner_approval_email,
    send_phone_otp_sms,
    check_messaging_credits,
)
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .serializers import (
    UserSerializer,
    OwnerRequestSerializer,
    AdminOwnerRequestSerializer,
    OwnerRequestVerifySerializer,
    OwnerRequestResendSerializer,
)
from .models import OwnerRequest
from django.conf import settings

logger = logging.getLogger(__name__)

User = get_user_model()


class ProfileView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

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
        operation_description="Submit a new request to become a property owner. Requires document upload and triggers SMS OTP.",
        tags=["Owner Requests"],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)

    def get_queryset(self):
        return OwnerRequest.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save(user=self.request.user)
        otp_code = generate_otp()
        cache_key = f"owner_otp_{instance.id}"

        # Cache OTP with resend count and 15m TTL
        cache_data = {
            "otp": otp_code,
            "resend_count": 0,
            "phone_number": instance.phone_number,
        }
        set_key(cache_key, cache_data, ttl=settings.CACHE_TTL)

        check_messaging_credits()
        try:
            send_phone_otp_sms(instance.phone_number, otp_code)
            logger.info(f"Owner request {instance.id} created. Phone OTP triggered.")
        except Exception as e:
            logger.error(f"Error triggering owner request SMS: {str(e)}")
            delete_key(cache_key)
            raise e


class OwnerRequestVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Verify Owner Request (SMS)",
        operation_description="Verify the phone number for an owner request using the SMS OTP.",
        tags=["Owner Requests"],
    )
    def post(self, request):
        serializer = OwnerRequestVerifySerializer(data=request.data)
        if serializer.is_valid():
            request_id = serializer.validated_data["request_id"]
            otp_code = serializer.validated_data["otp_code"]
            cache_key = f"owner_otp_{request_id}"

            cached_data = get_key(cache_key)
            if not cached_data or cached_data["otp"] != otp_code:
                logger.warning(f"Invalid OwnerRequest OTP attempt for ID {request_id}")
                return Response(
                    {"error": "Invalid or expired OTP."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            owner_request = get_object_or_404(
                OwnerRequest, id=request_id, user=request.user
            )
            owner_request.is_phone_verified = True
            owner_request.save()

            delete_key(cache_key)
            logger.info(f"Owner request {request_id} phone verified successfully.")

            return Response(
                {"message": "Phone number verified and request submitted for review."},
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OwnerRequestResendView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="Resend Owner Request OTP",
        operation_description="Resend the SMS verification OTP for a pending owner request.",
        tags=["Owner Requests"],
    )
    def post(self, request):
        serializer = OwnerRequestResendSerializer(data=request.data)
        if serializer.is_valid():
            request_id = serializer.validated_data["request_id"]
            cache_key = f"owner_otp_{request_id}"
            cached_data = get_key(cache_key)

            if not cached_data:
                return Response(
                    {"error": "Session expired or invalid request."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cached_data["resend_count"] >= 2:
                logger.warning(
                    f"Max resend limit reached for OwnerRequest {request_id}"
                )
                return Response(
                    {"error": "Max resend limit reached."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            new_otp = generate_otp()
            cached_data["otp"] = new_otp
            cached_data["resend_count"] += 1
            set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)

            check_messaging_credits()
            try:
                send_phone_otp_sms(cached_data["phone_number"], new_otp)
                logger.info(f"Resent OwnerRequest OTP for ID {request_id}")
                return Response({"message": "OTP resent."}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error triggering owner OTP resend: {str(e)}")
                return Response(
                    {"error": "Failed to resend SMS."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
