import logging
from django.db import transaction
import cloudinary.uploader
from django.contrib.auth import get_user_model
from django.conf import settings
from shared.cache_utils import set_key, get_key, delete_key
from shared.otp_utils import generate_otp
from shared.messaging import (
    send_otp_email,
    send_welcome_email,
    check_email_credits,
    notify_admin_new_owner_request,
    notify_user_owner_request_status,
)
from .models import OwnerRequest, Notification

logger = logging.getLogger(__name__)
User = get_user_model()


class AuthService:
    @staticmethod
    def trigger_signup_otp(email, validated_data):
        otp_code = generate_otp()
        cache_data = {
            "otp": otp_code,
            "user_data": validated_data,
            "attempts": 0,
        }
        set_key(f"signup_{email}", cache_data, ttl=settings.CACHE_TTL)
        check_email_credits()

        try:
            send_otp_email(email, otp_code)
            logger.info(f"Signup OTP successfully triggered for {email}")
            return True
        except Exception as e:
            logger.error(f"Error triggering signup OTP for {email}: {str(e)}")
            delete_key(f"signup_{email}")
            return False

    @staticmethod
    def verify_signup_otp(email, otp_code):
        cache_key = f"signup_{email}"
        cached_data = get_key(cache_key)

        if not cached_data:
            return None, "OTP expired or invalid."

        if cached_data["otp"] != otp_code:
            cached_data["attempts"] += 1
            set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)
            return None, "Invalid OTP."

        user_data = cached_data["user_data"]
        user = User.objects.create_user(**user_data)
        delete_key(cache_key)
        send_welcome_email(user.email, user.first_name)
        logger.info(f"User {user.email} verified and created successfully.")
        return user, None

    @staticmethod
    def resend_signup_otp(email):
        cache_key = f"signup_{email}"
        cached_data = get_key(cache_key)

        if not cached_data:
            return False, "Session expired, please signup again."

        new_otp = generate_otp()
        cached_data["otp"] = new_otp
        set_key(cache_key, cached_data, ttl=settings.CACHE_TTL)
        check_email_credits()

        try:
            send_otp_email(email, new_otp)
            logger.info(f"OTP successfully resent to {email}")
            return True, None
        except Exception as e:
            logger.error(f"Error triggering signup OTP resend for {email}: {str(e)}")
            return False, "Failed to resend OTP."

    @staticmethod
    def trigger_password_reset(email):
        user = User.objects.filter(email=email).first()
        if user:
            otp_code = generate_otp()
            set_key(f"reset_{email}", {"otp": otp_code}, ttl=settings.CACHE_TTL)
            check_email_credits()
            try:
                send_otp_email(email, otp_code)
                logger.info(f"Password reset OTP triggered for {email}")
                return True
            except Exception as e:
                logger.error(f"Error triggering reset OTP for {email}: {str(e)}")
                return False
        return True  # Return true even if user doesn't exist for security (avoid enumeration)


class OwnerRequestService:
    @staticmethod
    def create_request(user, validated_data):
        documents = validated_data.pop("documents", None)
        instance = OwnerRequest.objects.create(user=user, **validated_data)

        if documents:
            try:
                logger.info(f"Uploading owner documents for user {user.email}")
                upload_result = cloudinary.uploader.upload(
                    documents, folder="owner_documents/", resource_type="auto"
                )
                instance.documents_url = upload_result.get("secure_url")
                instance.save()
                logger.info(f"Cloudinary upload success: {instance.documents_url}")
            except Exception as e:
                logger.error(f"Cloudinary upload failed: {str(e)}")
                # In a real app we might delete the instance or raise error
                raise ValueError("Failed to upload documents.")

        logger.info(f"Owner request {instance.id} created for {user.email}")
        check_email_credits()
        notify_admin_new_owner_request(
            user_name=f"{user.first_name} {user.last_name}",
            user_email=user.email,
            id_type=instance.get_id_type_display(),
            reason=instance.reason,
        )
        return instance

    @staticmethod
    @transaction.atomic
    def process_request(request_instance, admin_user):
        if request_instance.status == OwnerRequest.Status.APPROVED:
            user = request_instance.user
            user.role = User.Role.OWNER
            user.is_verified_owner = True
            user.save()
            request_instance.is_verified = True
            request_instance.save()
            notify_user_owner_request_status(user.email, "APPROVED")
            logger.info(
                f"[OWNER_REQUEST] Admin {admin_user.email} APPROVED request for {user.email}"
            )
        elif request_instance.status == OwnerRequest.Status.REJECTED:
            notify_user_owner_request_status(
                request_instance.user.email,
                "REJECTED",
                reason=request_instance.admin_notes,
            )
            logger.info(
                f"[OWNER_REQUEST] Admin {admin_user.email} REJECTED request for {request_instance.user.email}"
            )


class NotificationService:
    @staticmethod
    def mark_as_read(notification, user):
        if notification.user != user:
            raise PermissionError("User does not own this notification.")
        notification.is_read = True
        notification.save()
        logger.info(
            f"[NOTIFICATION] Notification {notification.id} marked as read by user {user.email}"
        )
        return notification

    @staticmethod
    def mark_all_as_read(user):
        updated_count = Notification.objects.filter(user=user, is_read=False).update(
            is_read=True
        )
        logger.info(
            f"[NOTIFICATION] User {user.email} marked {updated_count} notifications as read."
        )
        return updated_count
