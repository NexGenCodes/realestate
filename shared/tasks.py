import logging
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

@shared_task
def send_email_task(subject, message, recipient_list, html_message_path=None, context=None, template_name=None):
    from django.core.mail import send_mail
    from django.template.loader import render_to_string
    
    logger.info(f"Preparing to send email to {recipient_list} with subject: {subject}")
    
    html_message = None
    template = html_message_path or template_name
    
    if template and context:
        try:
            html_message = render_to_string(template, context)
        except Exception as e:
            logger.error(f"Error rendering email template {template}: {str(e)}")
    
    try:
        send_mail(
            subject,
            message,
            settings.EMAIL_HOST_USER,
            recipient_list,
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Email successfully sent to {recipient_list}")
    except Exception as e:
        logger.error(f"Failed to send email to {recipient_list}: {str(e)}")
        raise e

@shared_task
def send_sms_task(phone, message):
    """
    Sends an SMS using Twilio. Fallbacks to simulation if credentials are missing.
    """
    from twilio.rest import Client
    
    sid = settings.TWILIO_ACCOUNT_SID
    token = settings.TWILIO_AUTH_TOKEN
    from_phone = settings.TWILIO_PHONE_NUMBER

    if not all([sid, token, from_phone]) or any(str(x).startswith('your_') for x in [sid, token, from_phone]):
        logger.info(f"--- SMS SIMULATION (Credentials Placeholder or Missing) ---")
        logger.info(f"TO: {phone}")
        logger.info(f"MESSAGE: {message}")
        logger.info(f"----------------------")
        return f"SMS simulated for {phone}"

    try:
        client = Client(sid, token)
        msg = client.messages.create(
            body=message,
            from_=from_phone,
            to=phone
        )
        logger.info(f"SMS successfully sent to {phone} via Twilio. SID: {msg.sid}")
        return f"SMS sent to {phone} via Twilio"
    except Exception as e:
        logger.error(f"Failed to send SMS to {phone} via Twilio: {str(e)}")
        # Log to console as fallback in case of API error
        logger.info(f"--- SMS FAILBACK SIMULATION ---")
        logger.info(f"TO: {phone}")
        logger.info(f"MESSAGE: {message}")
        raise e

@shared_task
def cleanup_stale_data():
    """
    Periodic task to clean up old data.
    """
    logger.info("Running system cleanup and health check...")
    # Future logic: Remove rejected OwnerRequests older than 30 days, etc.
    return "Cleanup check completed."
