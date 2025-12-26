import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from .tasks import send_low_credit_alert_task
from shared.cache_utils import get_key

logger = logging.getLogger(__name__)


def send_raw_email(subject, message, recipient_list, html_message=None):
    """Low-level wrapper for Django's EmailMultiAlternatives with Anymail header tracking."""
    from shared.cache_utils import set_key

    try:
        email = EmailMultiAlternatives(
            subject=subject,
            body=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=recipient_list,
        )
        if html_message:
            email.attach_alternative(html_message, "text/html")

        email.send(fail_silently=False)

        # Track Resend limits via anymail_status headers
        status = getattr(email, "anymail_status", None)
        if (
            status
            and hasattr(status, "esp_response")
            and status.esp_response is not None
        ):
            headers = status.esp_response.headers
            remaining = headers.get("ratelimit-remaining")
            limit = headers.get("ratelimit-limit")

            if remaining is not None and limit is not None:
                usage_data = {
                    "remaining": int(remaining),
                    "limit": int(limit),
                }
                # Cache the latest limit data for check_messaging_credits
                set_key("resend_usage_stats", usage_data, ttl=86400)  # 24h
                logger.info(f"Resend usage updated: {remaining}/{limit} remaining.")

        logger.info(f"Email successfully sent to {recipient_list}")
        return True
    except Exception as e:
        logger.error(f"Raw email delivery failed: {str(e)}")
        raise e


# --- High-Level Notification Wrappers ---


def send_otp_email(email, otp_code):
    """Triggers OTP email via background task."""
    from .tasks import send_email_task

    template = "users/emails/otp_email.html"
    context = {"otp_code": otp_code, "subject": "Your OTP Code"}
    html_content = render_to_string(template, context)

    send_email_task.delay(
        subject=context["subject"],
        message=f"Your OTP code is {otp_code}",
        recipient_list=[email],
        html_message=html_content,
    )


def send_welcome_email(email, user_name):
    """Triggers welcome email via background task."""
    from .tasks import send_email_task

    template = "users/emails/welcome_email.html"
    login_url = (
        f"https://{settings.ALLOWED_HOSTS[0]}/login/"
        if settings.ALLOWED_HOSTS
        else "http://localhost:8000/login/"
    )
    context = {
        "user_name": user_name,
        "login_url": login_url,
        "subject": "Welcome to Real Estate Pro!",
    }
    html_content = render_to_string(template, context)

    send_email_task.delay(
        subject=context["subject"],
        message=f"Welcome {user_name}!",
        recipient_list=[email],
        html_message=html_content,
    )


def send_owner_approval_email(email, user_name):
    """Triggers owner approval email via background task."""
    from .tasks import send_email_task

    template = "users/emails/owner_approval_email.html"
    login_url = (
        f"https://{settings.ALLOWED_HOSTS[0]}/login/"
        if settings.ALLOWED_HOSTS
        else "http://localhost:8000/login/"
    )
    context = {
        "user_name": user_name,
        "login_url": login_url,
        "subject": "Owner Request Approved!",
    }
    html_content = render_to_string(template, context)

    send_email_task.delay(
        subject=context["subject"],
        message=f"Congratulations {user_name}, your owner request has been approved!",
        recipient_list=[email],
        html_message=html_content,
    )


def notify_admin_new_owner_request(user_name, user_email, id_type, reason):
    """Notifies admin of a new owner request via email."""
    from .tasks import send_email_task

    subject = f"New Owner Request: {user_name}"
    message = f"""
A new owner request has been submitted.

User: {user_name}
Email: {user_email}
ID Type: {id_type}
Reason: {reason}

Please review this request in the admin panel.
    """
    logger.info(f"Admin notification triggered for owner request from {user_email}")
    send_email_task.delay(
        subject=subject,
        message=message,
        recipient_list=[settings.ADMIN_EMAIL],
        html_message=None,
    )


def notify_owner_property_status_change(email, property_title, new_status):
    """Notifies property owner of a status change (Rented/Sold)."""
    from .tasks import send_email_task

    subject = f"Property Status Update: {property_title}"
    message = f"Congratulations! Your property '{property_title}' has been successfully marked as {new_status}."

    send_email_task.delay(
        subject=subject,
        message=message,
        recipient_list=[email],
        html_message=None,  # Simplified for status update, can be themed later
    )


# --- Monitoring & Alerts ---


def check_email_credits():
    """Checks email balance and alerts admin if low."""
    email_usage = get_key("resend_usage_stats")
    if email_usage:
        remaining = email_usage.get("remaining", 0)
        limit = email_usage.get("limit", 0)
        # Alert if remaining is less than the configured threshold (e.g. 10 emails)
        if remaining < settings.RESEND_LOW_CREDIT_THRESHOLD:
            send_low_credit_alert_task.delay(
                "Email (Resend)",
                f"{remaining}/{limit}",
                settings.RESEND_LOW_CREDIT_THRESHOLD,
            )
    return {"email": email_usage}


def alert_admin_low_credits(provider, balance, threshold):
    """Synchronous internal call for alerting."""
    subject = f"CRITICAL: Low {provider} Balance"
    message = f"Your {provider} balance is currently {balance}, which is below the threshold of {threshold}."
    send_raw_email(subject, message, [settings.ADMIN_EMAIL])
