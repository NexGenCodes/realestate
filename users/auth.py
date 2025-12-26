import logging
from django.db import transaction
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from shared.cache_utils import set_key, get_key, delete_key
from shared.otp_utils import generate_otp
from shared.messaging import (
    send_otp_email,
    send_welcome_email,
    check_messaging_credits,
)
from .serializers import (
    SignupSerializer,
    VerifyOtpSerializer,
    ResendOtpSerializer,
    ForgotPasswordSerializer,
    ResetPasswordSerializer,
)

logger = logging.getLogger(__name__)
User = get_user_model()


class SignupView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp_request"

    @swagger_auto_schema(
        operation_summary="User Signup",
        operation_description="Register a new user by providing email, username, and password. Sends an OTP to the email.",
        tags=["Authentication"],
    )
    @transaction.atomic
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            otp_code = generate_otp()

            # Cache data: {otp, user_data, attempts}
            cache_data = {
                "otp": otp_code,
                "user_data": serializer.validated_data,
                "attempts": 0,
            }
            # Cache for 15 minutes
            set_key(f"signup_{email}", cache_data, ttl=settings.CACHE_TTL)

            # Check credits before proceeding (alerts admin if low)
            check_messaging_credits()

            try:
                # Strictly background to avoid blocking user response
                send_otp_email(email, otp_code)
                logger.info(f"Signup OTP successfully triggered for {email}")
                return Response(
                    {"message": "OTP sent to email."}, status=status.HTTP_201_CREATED
                )
            except Exception as e:
                logger.error(f"Error triggering signup OTP for {email}: {str(e)}")
                delete_key(f"signup_{email}")
                return Response(
                    {"error": "Failed to trigger OTP. Please try again later."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        logger.warning(f"Signup attempt failed with errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VerifySignupView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp_request"

    @swagger_auto_schema(
        operation_summary="Verify Signup",
        operation_description="Verify the signup OTP sent to the user's email to complete registration.",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            otp_code = serializer.validated_data["otp_code"]
            cache_key = f"signup_{email}"

            cached_data = get_key(cache_key)

            if not cached_data:
                return Response(
                    {"error": "OTP expired or invalid."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if cached_data["otp"] != otp_code:
                cached_data["attempts"] += 1
                set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)
                return Response(
                    {"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST
                )

            # Create User
            user_data = cached_data["user_data"]
            user = User.objects.create_user(**user_data)

            delete_key(cache_key)
            send_welcome_email(user.email, user.first_name)
            logger.info(f"User {user.username} verified and created successfully.")

            return Response(
                {"message": "Account created successfully."},
                status=status.HTTP_201_CREATED,
            )
        logger.warning(
            f"Signup verification failed for {request.data.get('email', 'unknown')}"
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResendOtpView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp_request"

    @swagger_auto_schema(
        operation_summary="Resend Signup OTP",
        operation_description="Resend the verification OTP for a pending signup.",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = ResendOtpSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            cache_key = f"signup_{email}"
            cached_data = get_key(cache_key)

            if not cached_data:
                return Response(
                    {"error": "Session expired, please signup again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            new_otp = generate_otp()
            cached_data["otp"] = new_otp
            set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)

            check_messaging_credits()
            try:
                send_otp_email(email, new_otp)
                logger.info(f"OTP successfully resent to {email}")
                return Response({"message": "OTP resent."}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(
                    f"Error triggering signup OTP resend for {email}: {str(e)}"
                )
                return Response(
                    {"error": "Failed to resend OTP."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "otp_request"

    @swagger_auto_schema(
        operation_summary="Forgot Password",
        operation_description="Trigger a password reset OTP for the provided email address.",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            user = User.objects.filter(email=email).first()
            if user:
                otp_code = generate_otp()
                set_key(f"reset_{email}", {"otp": otp_code}, ttl=settings.CACHE_TTL)
                check_messaging_credits()
                try:
                    send_otp_email(email, otp_code)
                    logger.info(f"Password reset OTP triggered for {email}")
                except Exception as e:
                    logger.error(f"Error triggering reset OTP for {email}: {str(e)}")
            # Always return 200 for security
            return Response(
                {"message": "If account exists, OTP sent."}, status=status.HTTP_200_OK
            )
        logger.warning(
            f"Forgot password attempt failed with errors: {serializer.errors}"
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    @swagger_auto_schema(
        operation_summary="Reset Password",
        operation_description="Reset the user's password using the OTP from the 'Forgot Password' flow.",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            otp_code = serializer.validated_data["otp_code"]
            new_password = serializer.validated_data["new_password"]

            cache_key = f"reset_{email}"
            cached_data = get_key(cache_key)

            if not cached_data or cached_data["otp"] != otp_code:
                return Response(
                    {"error": "Invalid or expired OTP."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            delete_key(cache_key)
            logger.info(f"Password reset successful for {email}")

            return Response(
                {"message": "Password reset successfully."}, status=status.HTTP_200_OK
            )
        logger.warning(
            f"Password reset attempt failed for {request.data.get('email', 'unknown')}"
        )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
