from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import OwnerRequest

User = get_user_model()

class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'password')

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value

class VerifyOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)

class ResendOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'first_name', 'last_name', 'role', 'profile_picture', 'country', 'gender', 'phone_number', 'bio')
        read_only_fields = ('role',)

    def validate_profile_picture(self, value):
        if value:
            # 1. Validation: File Type
            import os
            ext = os.path.splitext(value.name)[1].lower()
            if ext not in ['.jpg', '.jpeg', '.png']:
                raise serializers.ValidationError("Unsupported file extension. Allowed: .jpg, .jpeg, .png")
            
            # 2. Validation: File Size (Max 5MB)
            limit_mb = 5
            if value.size > limit_mb * 1024 * 1024:
                raise serializers.ValidationError(f"File size too large. Max size is {limit_mb}MB.")
        
        return value

class OwnerRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = OwnerRequest
        fields = ('id', 'user', 'documents', 'phone_number', 'status', 'is_phone_verified', 'is_verified', 'created_at')
        read_only_fields = ('user', 'status', 'is_phone_verified', 'is_verified', 'created_at')

    def validate(self, data):
        user = self.context['request'].user
        if user.role == User.Role.OWNER:
            raise serializers.ValidationError("You are already a property owner.")
        
        if OwnerRequest.objects.filter(user=user, status=OwnerRequest.Status.PENDING).exists():
            raise serializers.ValidationError("You already have a pending ownership request.")
        
        return data

    def validate_documents(self, value):
        # 1. Validation: File Type
        import os
        ext = os.path.splitext(value.name)[1].lower()
        if ext not in ['.pdf', '.jpg', '.jpeg', '.png']:
             raise serializers.ValidationError("Unsupported file extension. Allowed: .pdf, .jpg, .jpeg, .png")
        
        # 2. Validation: File Size (Max 5MB)
        limit_mb = 5
        if value.size > limit_mb * 1024 * 1024:
            raise serializers.ValidationError(f"File size too large. Max size is {limit_mb}MB.")
        
        return value

class OwnerRequestVerifySerializer(serializers.Serializer):
    request_id = serializers.IntegerField()
    otp_code = serializers.CharField(max_length=6)

class OwnerRequestResendSerializer(serializers.Serializer):
    request_id = serializers.IntegerField()

class AdminOwnerRequestSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    class Meta:
        model = OwnerRequest
        fields = ('id', 'user', 'user_username', 'documents', 'phone_number', 'status', 'is_phone_verified', 'is_verified', 'created_at')
        read_only_fields = ('user', 'documents', 'phone_number', 'is_phone_verified', 'is_verified', 'created_at')

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(write_only=True, validators=[validate_password])
