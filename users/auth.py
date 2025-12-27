import logging
from django.db import transaction
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework import status, permissions
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework.response import Response
from rest_framework.views import APIView
from drf_yasg.utils import swagger_auto_schema
from rest_framework_simplejwt.tokens import RefreshToken
from .services import AuthService
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
            success = AuthService.trigger_signup_otp(email, serializer.validated_data)

            if success:
                return Response(
                    {"message": "OTP sent to email."}, status=status.HTTP_201_CREATED
                )
            else:
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
        operation_description="Verify the signup OTP sent to the user's email to complete registration and receive JWT tokens.",
        tags=["Authentication"],
    )
    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            otp_code = serializer.validated_data["otp_code"]

            user, error_msg = AuthService.verify_signup_otp(email, otp_code)

            if user:
                # Generate JWT tokens for the newly created user
                refresh = RefreshToken.for_user(user)

                return Response(
                    {
                        "message": "Account created successfully.",
                        "tokens": {
                            "refresh": str(refresh),
                            "access": str(refresh.access_token),
                        },
                    },
                    status=status.HTTP_201_CREATED,
                )
            else:
                return Response(
                    {"error": error_msg},
                    status=status.HTTP_400_BAD_REQUEST,
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
            success, error_msg = AuthService.resend_signup_otp(email)

            if success:
                return Response({"message": "OTP resent."}, status=status.HTTP_200_OK)
            else:
                return Response(
                    {"error": error_msg},
                    status=(
                        status.HTTP_400_BAD_REQUEST
                        if "expired" in error_msg
                        else status.HTTP_500_INTERNAL_SERVER_ERROR
                    ),
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
            AuthService.trigger_password_reset(email)
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
    throttle_scope = "otp_request"

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


class CustomTokenObtainPairView(TokenObtainPairView):
    throttle_scope = "login_attempt"

    def post(self, request, *args, **kwargs):
        email = request.data.get("email", "unknown")
        try:
            response = super().post(request, *args, **kwargs)
            if response.status_code == 200:
                logger.info(f"Successful login for user: {email}")
            return response
        except Exception as e:
            logger.warning(f"Failed login attempt for user: {email}. Error: {str(e)}")
            raise e
