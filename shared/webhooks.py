import requests
import logging
import json
from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)

# Note: In a real system, we would have a WebhookSubscription model where users
# register their own URLs. For Phase 3, we implement the dispatcher architecture.


@shared_task
def dispatch_webhook(event_type, payload, target_url=None):
    """
    Sends a JSON payload to a target URL when an event occurs.
    """
    if not target_url:
        # Fallback to a global webhook log or a configured default for now
        target_url = getattr(settings, "DEFAULT_WEBHOOK_URL", None)

    if not target_url:
        logger.warning(f"No target URL for webhook {event_type}")
        return False

    try:
        response = requests.post(
            target_url,
            json={
                "event": event_type,
                "data": payload,
                "timestamp": (
                    json.dumps(payload.get("timestamp"), default=str)
                    if payload.get("timestamp")
                    else None
                ),
            },
            timeout=10,
        )
        response.raise_for_status()
        logger.info(f"Webhook {event_type} sent to {target_url} successfully.")
        return True
    except Exception as e:
        logger.error(f"Failed to send webhook {event_type} to {target_url}: {str(e)}")
        return False


def trigger_event(event_type, payload):
    """
    Helper to trigger webhooks.
    """
    # Logic to find subscribers for this event_type would go here.
    # For now, we dispatch to the default if configured.
    dispatch_webhook.delay(event_type, payload)
