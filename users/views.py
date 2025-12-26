import logging
from django.db import transaction
from rest_framework import status, generics, viewsets, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from shared.cache_utils import set_key, get_key, delete_key
from shared.otp_utils import generate_otp
from shared.notification_utils import (
    send_otp_email, send_welcome_email, 
    send_owner_approval_email, send_phone_otp_sms
)
from .serializers import (
    SignupSerializer, VerifyOtpSerializer, ResendOtpSerializer,
    UserSerializer, OwnerRequestSerializer, AdminOwnerRequestSerializer, 
    OwnerRequestVerifySerializer, OwnerRequestResendSerializer,
    ForgotPasswordSerializer, ResetPasswordSerializer
)
from .models import OwnerRequest
from django.conf import settings

logger = logging.getLogger(__name__)

User = get_user_model()

class SignupView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'otp_request'
    @transaction.atomic
    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp_code = generate_otp()
            
            # Cache data: {otp, user_data, attempts}
            cache_data = {
                'otp': otp_code,
                'user_data': serializer.validated_data,
                'attempts': 0
            }
            # Cache for 15 minutes
            set_key(f"signup_{email}", cache_data, ttl=settings.CACHE_TTL)
            
            try:
                # synchronous call to ensure immediate error if email fails
                send_otp_email(email, otp_code, sync=True)
                logger.info(f"Signup OTP sent to {email}")
                return Response({"message": "OTP sent to email."}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error sending signup OTP to {email}: {str(e)}")
                # Transaction will rollback if this fails, and we delete cache to be clean
                delete_key(f"signup_{email}")
                return Response({"error": "Failed to send OTP. Please try again later."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        logger.warning(f"Signup attempt failed with errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class VerifySignupView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'otp_request'
    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp_code = serializer.validated_data['otp_code']
            cache_key = f"signup_{email}"
            
            cached_data = get_key(cache_key)
            
            if not cached_data:
                return Response({"error": "OTP expired or invalid."}, status=status.HTTP_400_BAD_REQUEST)
            
            if cached_data['otp'] != otp_code:
                cached_data['attempts'] += 1
                set_key(cache_key, cached_data, ttl=settings.CACHE_TTL) # Reset TTL or keep? Simplified here.
                return Response({"error": "Invalid OTP."}, status=status.HTTP_400_BAD_REQUEST)

            # Create User
            user_data = cached_data['user_data']
            user = User.objects.create_user(**user_data)
            
            delete_key(cache_key)
            send_welcome_email(user.email, user.first_name)
            logger.info(f"User {user.username} verified and created successfully.")
            
            return Response({"message": "Account created successfully."}, status=status.HTTP_201_CREATED)
        logger.warning(f"Signup verification failed for {request.data.get('email', 'unknown')}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResendOtpView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'otp_request'
    def post(self, request):
        serializer = ResendOtpSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            cache_key = f"signup_{email}"
            cached_data = get_key(cache_key)
            
            if not cached_data:
                 return Response({"error": "Session expired, please signup again."}, status=status.HTTP_400_BAD_REQUEST)
            
            new_otp = generate_otp()
            cached_data['otp'] = new_otp
            set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)
            
            try:
                send_otp_email(email, new_otp, sync=True)
                return Response({"message": "OTP resent."}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error resending signup OTP to {email}: {str(e)}")
                return Response({"error": "Failed to resend OTP."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProfileView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = UserSerializer

    def get_object(self):
        logger.debug(f"Profile access for user {self.request.user.username}")
        return self.request.user

    @transaction.atomic
    def perform_update(self, serializer):
        # File upload to S3 happens here if profile_picture is in validated_data
        serializer.save()

class OwnerRequestView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = OwnerRequestSerializer

    def get_queryset(self):
        return OwnerRequest.objects.filter(user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        instance = serializer.save(user=self.request.user)
        otp_code = generate_otp()
        cache_key = f"owner_otp_{instance.id}"
        
        # Cache OTP with resend count and 15m TTL
        cache_data = {
            'otp': otp_code,
            'resend_count': 0,
            'phone_number': instance.phone_number
        }
        set_key(cache_key, cache_data, ttl=settings.CACHE_TTL)
        
        try:
            send_phone_otp_sms(instance.phone_number, otp_code, sync=True)
            logger.info(f"Owner request {instance.id} created for user {self.request.user.username}. Phone OTP sent.")
        except Exception as e:
            logger.error(f"Error sending owner request SMS to {instance.phone_number}: {str(e)}")
            # Rollback will happen due to atomic, also clean cache
            delete_key(cache_key)
            raise e # Reraise to let DRF/Django handle error response or transaction fail

class OwnerRequestVerifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = OwnerRequestVerifySerializer(data=request.data)
        if serializer.is_valid():
            request_id = serializer.validated_data['request_id']
            otp_code = serializer.validated_data['otp_code']
            cache_key = f"owner_otp_{request_id}"
            
            cached_data = get_key(cache_key)
            if not cached_data or cached_data['otp'] != otp_code:
                logger.warning(f"Invalid OwnerRequest OTP attempt for ID {request_id}")
                return Response({"error": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)
            
            owner_request = get_object_or_404(OwnerRequest, id=request_id, user=request.user)
            owner_request.is_phone_verified = True
            owner_request.save()
            
            delete_key(cache_key)
            logger.info(f"Owner request {request_id} phone verified successfully.")
            
            return Response({"message": "Phone number verified and request submitted for review."}, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class OwnerRequestResendView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = OwnerRequestResendSerializer(data=request.data)
        if serializer.is_valid():
            request_id = serializer.validated_data['request_id']
            cache_key = f"owner_otp_{request_id}"
            cached_data = get_key(cache_key)
            
            if not cached_data:
                return Response({"error": "Session expired or invalid request."}, status=status.HTTP_400_BAD_REQUEST)
            
            if cached_data['resend_count'] >= 2:
                logger.warning(f"Max resend limit reached for OwnerRequest {request_id}")
                return Response({"error": "Max resend limit reached."}, status=status.HTTP_400_BAD_REQUEST)
            
            new_otp = generate_otp()
            cached_data['otp'] = new_otp
            cached_data['resend_count'] += 1
            set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)
            
            try:
                send_phone_otp_sms(cached_data['phone_number'], new_otp, sync=True)
                logger.info(f"Resent OwnerRequest OTP for ID {request_id} (Attempt {cached_data['resend_count']})")
                return Response({"message": "OTP resent."}, status=status.HTTP_200_OK)
            except Exception as e:
                logger.error(f"Error resending owner OTP to {cached_data['phone_number']}: {str(e)}")
                return Response({"error": "Failed to resend SMS."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AdminOwnerRequestViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = OwnerRequest.objects.all()
    serializer_class = AdminOwnerRequestSerializer
    http_method_names = ['get', 'put', 'patch', 'head', 'options']

    @transaction.atomic
    def perform_update(self, serializer):
        instance = serializer.save()
        if instance.status == OwnerRequest.Status.APPROVED:
            instance.user.role = User.Role.OWNER
            instance.user.save()
            instance.is_verified = True
            instance.save()
            # Email can be async as it's not blocking the critical flow for the admin
            send_owner_approval_email(instance.user.email, instance.user.first_name)
            logger.info(f"Admin approved OwnerRequest {instance.id} for user {instance.user.username}")

class AdminUserViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAdminUser]
    queryset = User.objects.all()
    serializer_class = UserSerializer

class ForgotPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'otp_request'
    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            user = User.objects.filter(email=email).first()
            if user:
                 otp_code = generate_otp()
                 set_key(f"reset_{email}", {'otp': otp_code}, ttl=settings.CACHE_TTL)
                 try:
                     send_otp_email(email, otp_code, sync=True)
                     logger.info(f"Password reset OTP sent to {email}")
                 except Exception as e:
                     logger.error(f"Error sending reset OTP to {email}: {str(e)}")
                     # We return 200 anyway for security but log the failure
            # Always return 200 for security
            return Response({"message": "If account exists, OTP sent."}, status=status.HTTP_200_OK)
        logger.warning(f"Forgot password attempt failed with errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ResetPasswordView(APIView):
    permission_classes = [permissions.AllowAny]
    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data['email']
            otp_code = serializer.validated_data['otp_code']
            new_password = serializer.validated_data['new_password']
            
            cache_key = f"reset_{email}"
            cached_data = get_key(cache_key)
            
            if not cached_data or cached_data['otp'] != otp_code:
                 return Response({"error": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)
            
            user = User.objects.get(email=email)
            user.set_password(new_password)
            user.save()
            delete_key(cache_key)
            logger.info(f"Password reset successful for {email}")
            
            return Response({"message": "Password reset successfully."}, status=status.HTTP_200_OK)
        logger.warning(f"Password reset attempt failed for {request.data.get('email', 'unknown')}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
