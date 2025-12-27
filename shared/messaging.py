import logging
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
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


def notify_owner_new_tour_request(owner_email, property_title, requester_email, slot):
    """Notifies property owner of a new tour request via email and in-app notification."""
    from .tasks import send_email_task
    from users.models import Notification, User

    subject = f"New Tour Request: {property_title}"
    message = f"""
Hello,

You have a new tour request for your property: {property_title}.

Requester: {requester_email}
Requested Slot: {slot}

Please log in to your dashboard to approve or reject this request.
    """

    # Send Email
    send_email_task.delay(
        subject=subject,
        message=message,
        recipient_list=[owner_email],
        html_message=None,
    )

    # In-App & Push Notification
    try:
        from users.models import User
        from shared.notifications import send_push_notification

        user = User.objects.get(email=owner_email)
        send_push_notification(
            user=user,
            title="New Tour Request",
            body=f"{requester_email} wants to tour '{property_title}' at {slot}.",
            data={"type": "tour_request"},
        )
    except User.DoesNotExist:
        logger.error(f"Could not create notification: User {owner_email} not found.")


def notify_user_owner_request_status(user_email, status, reason=None):
    """Notifies user when their owner request is approved or rejected."""
    from .tasks import send_email_task
    from users.models import Notification, User

    subject = f"Owner Request {status.capitalize()}"
    body_text = f"Your request to become a property owner has been {status}."
    if reason:
        body_text += f"\nReason: {reason}"

    # Send Email
    send_email_task.delay(
        subject=subject,
        message=body_text,
        recipient_list=[user_email],
        html_message=None,
    )

    # In-App & Push Notification
    try:
        from users.models import User
        from shared.notifications import send_push_notification

        user = User.objects.get(email=user_email)
        send_push_notification(
            user=user,
            title=f"Owner Request {status.capitalize()}",
            body=body_text,
            data={"type": "owner_request_update", "status": status},
        )
    except User.DoesNotExist:
        logger.error(f"Could not create notification: User {user_email} not found.")


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

    # In-App & Push Notification
    try:
        from users.models import User
        from shared.notifications import send_push_notification

        user = User.objects.get(email=email)
        send_push_notification(
            user=user,
            title="Property Status Update",
            body=message,
            data={"type": "property_status_change", "property": property_title},
        )
    except User.DoesNotExist:
        pass


# --- Monitoring & Alerts ---


def check_email_credits():
    """Checks email balance and alerts admin if low."""
    email_usage = get_key("resend_usage_stats")
    if email_usage:
        remaining = email_usage.get("remaining", 0)
        limit = email_usage.get("limit", 0)
        # Alert if remaining is less than the configured threshold (e.g. 10 emails)
        if remaining < settings.RESEND_LOW_CREDIT_THRESHOLD:
            from .tasks import send_low_credit_alert_task

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


# --- Payment & Financial Notifications ---


def notify_payment_success(transaction):
    """Notify buyer and owner of a successful payment."""
    from shared.notifications import send_push_notification
    from .tasks import send_email_task

    # 1. Notify Buyer (Confirmation)
    buyer_subject = f"Payment Confirmed: {transaction.property.title}"
    buyer_msg = f"Your payment of NGN {transaction.amount:,.2f} for '{transaction.property.title}' has been received."

    send_push_notification(
        user=transaction.payer,
        title="Payment Successful",
        body=buyer_msg,
        data={"type": "payment_success", "transaction_id": transaction.id},
    )
    send_email_task.delay(buyer_subject, buyer_msg, [transaction.payer.email])

    # 2. Notify Owner (New Sale)
    owner_subject = f"New Sale: {transaction.property.title}"
    owner_msg = f"You have a new sale! NGN {transaction.owner_amount:,.2f} has been added to your escrow. Funds will be available in 7 days."

    send_push_notification(
        user=transaction.owner,
        title="New Sale Received",
        body=owner_msg,
        data={"type": "sale_received", "transaction_id": transaction.id},
    )
    send_email_task.delay(owner_subject, owner_msg, [transaction.owner.email])


def notify_funds_released(transaction):
    """Notify owner when escrow period ends."""
    from shared.notifications import send_push_notification
    from .tasks import send_email_task

    subject = "Funds Available for Withdrawal"
    msg = f"Escrow complete! NGN {transaction.owner_amount:,.2f} from the sale of '{transaction.property.title}' is now available in your wallet."

    send_push_notification(
        user=transaction.owner,
        title="Funds Released",
        body=msg,
        data={"type": "funds_released", "transaction_id": transaction.id},
    )
    send_email_task.delay(subject, msg, [transaction.owner.email])


def notify_withdrawal_status(withdrawal):
    """Notify user of withdrawal processing result."""
    from shared.notifications import send_push_notification
    from .tasks import send_email_task

    status_str = "Successful" if withdrawal.status == "PROCESSED" else "Failed"
    subject = f"Withdrawal {status_str}"

    if withdrawal.status == "PROCESSED":
        msg = f"Your withdrawal of NGN {withdrawal.amount:,.2f} has been processed successfully."
    else:
        msg = f"Your withdrawal request of NGN {withdrawal.amount:,.2f} failed. {withdrawal.admin_note}"

    send_push_notification(
        user=withdrawal.user,
        title=f"Withdrawal {status_str}",
        body=msg,
        data={"type": "withdrawal_update", "status": withdrawal.status},
    )
    send_email_task.delay(subject, msg, [withdrawal.user.email])
