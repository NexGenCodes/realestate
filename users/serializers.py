import logging
import cloudinary.uploader
from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from .models import OwnerRequest

logger = logging.getLogger(__name__)
User = get_user_model()


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])

    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "password")

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            logger.info(f"Signup validation failed: Email {value} already exists.")
            raise serializers.ValidationError("A user with this email already exists.")
        return value


class VerifyOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)


class ResendOtpSerializer(serializers.Serializer):
    email = serializers.EmailField()


class UserSerializer(serializers.ModelSerializer):
    profile_picture = serializers.ImageField(write_only=True, required=False)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "role",
            "profile_picture",
            "profile_picture_url",
            "country",
            "gender",
            "phone_number",
            "bio",
        )
        read_only_fields = ("role", "profile_picture_url")

    def validate_profile_picture(self, value):
        if value:
            limit_mb = 5
            if value.size > limit_mb * 1024 * 1024:
                logger.warning(f"Profile picture size check failed: {value.size} bytes")
                raise serializers.ValidationError(
                    f"File size too large. Max size is {limit_mb}MB."
                )
        return value

    def update(self, instance, validated_data):
        profile_picture = validated_data.pop("profile_picture", None)
        if profile_picture:
            try:
                logger.info(f"Uploading profile picture for user {instance.username}")
                upload_result = cloudinary.uploader.upload(
                    profile_picture, folder="profile_pics/"
                )
                instance.profile_picture_url = upload_result.get("secure_url")
                logger.info(
                    f"Cloudinary upload success: {instance.profile_picture_url}"
                )
            except Exception as e:
                logger.error(
                    f"Cloudinary upload failed for {instance.username}: {str(e)}"
                )
                raise serializers.ValidationError("Failed to upload image.")

        return super().update(instance, validated_data)


class OwnerRequestSerializer(serializers.ModelSerializer):
    documents = serializers.FileField(write_only=True)

    class Meta:
        model = OwnerRequest
        fields = (
            "id",
            "user",
            "id_type",
            "documents",
            "documents_url",
            "reason",
            "status",
            "is_verified",
            "created_at",
        )
        read_only_fields = (
            "user",
            "status",
            "is_verified",
            "created_at",
            "documents_url",
        )

    def validate_documents(self, value):
        if value:
            import os

            ext = os.path.splitext(value.name)[1].lower()
            if ext not in [".pdf", ".jpg", ".jpeg", ".png"]:
                raise serializers.ValidationError(
                    "Unsupported file extension. Allowed: .pdf, .jpg, .jpeg, .png"
                )

            limit_mb = 5
            if value.size > limit_mb * 1024 * 1024:
                raise serializers.ValidationError(
                    f"File size too large. Max size is {limit_mb}MB."
                )
        return value

    def create(self, validated_data):
        documents = validated_data.pop("documents", None)
        instance = OwnerRequest(**validated_data)

        if documents:
            try:
                # We need the user from context for logging
                user = self.context["request"].user
                logger.info(f"Uploading owner documents for user {user.username}")
                upload_result = cloudinary.uploader.upload(
                    documents, folder="owner_documents/", resource_type="auto"
                )
                instance.documents_url = upload_result.get("secure_url")
                logger.info(f"Cloudinary upload success: {instance.documents_url}")
            except Exception as e:
                logger.error(f"Cloudinary upload failed: {str(e)}")
                raise serializers.ValidationError("Failed to upload documents.")

        instance.save()
        return instance


class AdminOwnerRequestSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source="user.username", read_only=True)

    class Meta:
        model = OwnerRequest
        fields = (
            "id",
            "user",
            "user_username",
            "id_type",
            "documents_url",
            "reason",
            "status",
            "is_verified",
            "created_at",
        )
        read_only_fields = (
            "user",
            "is_verified",
            "created_at",
            "documents_url",
        )


class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField(max_length=6)
    new_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )

    def validate(self, data):
        # We can add a log here if needed, but the view usually handles the logic
        return data
