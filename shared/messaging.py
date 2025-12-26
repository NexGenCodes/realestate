import logging
import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
import sms
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


def send_raw_sms(phone, message):
    """Low-level wrapper for django-sms."""
    try:
        sms.send_sms(body=message, from_phone="REPro", to=[phone], fail_silently=False)
        logger.info(f"SMS successfully sent to {phone}")
        return True
    except Exception as e:
        logger.error(f"Raw SMS delivery failed: {str(e)}")
        raise e


# --- High-Level Notification Wrappers ---


def get_base_context(extra_context=None):
    context = {}
    if extra_context:
        context.update(extra_context)
    return context


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


def send_phone_otp_sms(phone, otp):
    """Triggers phone OTP SMS via background task."""
    from .tasks import send_sms_task

    message = f"Your Real Estate verification code is: {otp}. Valid for 15 minutes."
    send_sms_task.delay(phone, message)


# --- Monitoring & Alerts ---


def check_messaging_credits():
    """Checks balances and alerts admin if low."""

    # SMS Check
    sms_balance = None
    try:
        if settings.DEBUG:
            api_token = settings.BULKSMSNIGERIA_API_TOKEN
            if api_token and not api_token.startswith("your_"):
                url = f"https://www.bulksmsnigeria.com/api/v1/user/balance?api_token={api_token}"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    sms_balance = float(res.json().get("data", {}).get("balance", 0))
        else:
            api_key = settings.TERMII_API_KEY
            if api_key and not api_key.startswith("your_"):
                url = f"https://api.ng.termii.com/api/get-balance?api_key={api_key}"
                res = requests.get(url, timeout=5)
                if res.status_code == 200:
                    sms_balance = float(res.json().get("balance", 0))

        if sms_balance is not None and sms_balance < settings.SMS_LOW_CREDIT_THRESHOLD:
            send_low_credit_alert_task.delay(
                "SMS", sms_balance, settings.SMS_LOW_CREDIT_THRESHOLD
            )
    except Exception as e:
        logger.error(f"Error checking SMS balance: {str(e)}")

    # Email Check (Header-based from cache)
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

    return {"sms": sms_balance, "email": email_usage}


def alert_admin_low_credits(provider, balance, threshold):
    """Synchronous internal call for alerting."""
    subject = f"CRITICAL: Low {provider} Balance"
    message = f"Your {provider} balance is currently {balance}, which is below the threshold of {threshold}."
    send_raw_email(subject, message, [settings.ADMIN_EMAIL])
