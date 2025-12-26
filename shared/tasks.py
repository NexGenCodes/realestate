import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task
def send_email_task(subject, message, recipient_list, html_message=None):
    """Background task to send email via messaging hub."""
    from .messaging import send_raw_email

    logger.info(f"Starting send_email_task for: {recipient_list}")
    result = send_raw_email(subject, message, recipient_list, html_message)
    logger.info(f"Finished send_email_task for: {recipient_list}. Result: {result}")
    return result


@shared_task
def send_low_credit_alert_task(provider, balance, threshold):
    """Background task for low credit alerts."""
    from .messaging import alert_admin_low_credits

    return alert_admin_low_credits(provider, balance, threshold)


@shared_task
def cleanup_stale_data():
    """
    Periodic task to clean up old data.
    """
    logger.info("Running system cleanup and health check...")
    # Future logic: Remove rejected OwnerRequests older than 30 days, etc.
    return "Cleanup check completed."
