import logging
from .tasks import send_push_notification_task

logger = logging.getLogger(__name__)


def send_push_notification(user, title, body, data=None):
    """
    Trigger async push notification task.
    Takes a User object, extracts ID, and calls Celery.
    """
    try:
        # .delay() is the standard Celery way to offload to a worker
        send_push_notification_task.delay(user.id, title, body, data)
        logger.debug(f"Queued push notification for user {user.id}")
    except Exception as e:
        logger.error(f"Failed to queue push notification: {e}")
        # Fallback: We could run synchronously here if critical,
        # but for notifications, failing silent or retry is usually ok.
