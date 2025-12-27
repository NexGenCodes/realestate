import logging
from celery import shared_task
from django.contrib.auth import get_user_model
from users.models import Notification
from fcm_django.models import FCMDevice
from firebase_admin.messaging import Message, Notification as FCMNotification
from django_redis import get_redis_connection
from properties.models import Property
from django.db.models import F
from users.models import Notification
from django.utils import timezone
from datetime import timedelta
from .messaging import send_raw_email
from .messaging import alert_admin_low_credits


logger = logging.getLogger(__name__)


@shared_task
def send_email_task(subject, message, recipient_list, html_message=None):
    """Background task to send email via messaging hub."""

    logger.info(f"Starting send_email_task for: {recipient_list}")
    result = send_raw_email(subject, message, recipient_list, html_message)
    logger.info(f"Finished send_email_task for: {recipient_list}. Result: {result}")
    return result


@shared_task
def send_low_credit_alert_task(provider, balance, threshold):
    """Background task for low credit alerts."""

    return alert_admin_low_credits(provider, balance, threshold)


@shared_task
def cleanup_stale_data():
    """
    Periodic task to clean up old data and keep DB lean.
    """

    logger.info("Running system cleanup...")

    # 1. Clear notifications older than 30 days
    threshold = timezone.now() - timedelta(days=30)
    deleted_count, _ = Notification.objects.filter(created_at__lt=threshold).delete()

    logger.info(f"Cleanup finished. Removed {deleted_count} old notifications.")
    return f"Cleanup completed. Deleted {deleted_count} items."


@shared_task
def sync_view_counts():
    """
    Sync accumulated view counts from Redis to Postgres.
    """

    con = get_redis_connection("default")

    # Get all properties that have new views
    # 'spop' pops a member, but we might want to process a batch.
    # 'smembers' gets all, then we process.
    dirty_ids = con.smembers("property_views_dirty")

    if not dirty_ids:
        return "No views to sync."

    count_updates = 0
    for prop_id_bytes in dirty_ids:
        prop_id = int(prop_id_bytes)
        cache_key = f"property_view_count:{prop_id}"

        # Atomic get and reset to 0
        # getset returns the *old* value.
        views = con.getset(cache_key, 0)

        if views and int(views) > 0:
            Property.objects.filter(pk=prop_id).update(
                views_count=F("views_count") + int(views)
            )
            count_updates += 1

        # Remove from dirty set
        con.srem("property_views_dirty", prop_id)

    logger.info(f"Synced views for {count_updates} properties.")
    return f"Synced {count_updates} properties."


@shared_task
def send_push_notification_task(user_id, title, body, data=None):
    """
    Async task to send push notifications via FCM.
    """
    User = get_user_model()
    try:
        user = User.objects.get(id=user_id)
    except User.DoesNotExist:
        logger.warning(f"User {user_id} not found for push notification.")
        return "User not found"

    if data is None:
        data = {}

    # 1. Persist to Database
    try:
        Notification.objects.create(user=user, title=title, body=body, data=data)
    except Exception as e:
        logger.error(f"Failed to save notification to DB: {e}")

    # 2. Send via FCM
    devices = FCMDevice.objects.filter(user=user, active=True)
    if not devices.exists():
        return f"No active devices for user {user.email}"

    try:
        # Send to all user devices
        # Note: Sending batch messages or topics is more efficient for mass broadcasts,
        # but for single user, this loop or devices.send_message is fine.
        devices.send_message(
            Message(notification=FCMNotification(title=title, body=body), data=data)
        )
        logger.info(f"Push notification sent to {user.email}: {title}")
        return f"Sent to {user.email}"
    except Exception as e:
        logger.error(f"Failed to send push notification to {user.email}: {e}")
        return f"Failed: {e}"
