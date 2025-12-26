import logging
import requests
from sms.backends.base import BaseSmsBackend

logger = logging.getLogger(__name__)


class BulkSMSNigeriaBackend(BaseSmsBackend):
    def send_messages(self, messages):
        from django.conf import settings

        api_token = settings.BULKSMSNIGERIA_API_TOKEN
        if not api_token or api_token.startswith("your_"):
            logger.warning(
                "BulkSMSNigeria: API Token not configured. Simulating success."
            )
            return len(messages)

        count = 0
        for msg in messages:
            try:
                payload = {
                    "api_token": api_token,
                    "from": msg.from_phone or "REPro",
                    "to": ",".join(msg.to),
                    "body": msg.body,
                    "dnd": 2,  # Try to bypass DND
                }
                logger.info(f"BulkSMSNigeria: Sending to {msg.to}")
                response = requests.post(
                    "https://www.bulksmsnigeria.com/api/v1/sms/create",
                    json=payload,
                    timeout=10,
                )
                if response.status_code == 200:
                    count += 1
                    logger.info("BulkSMSNigeria: Send successful.")
                else:
                    logger.error(
                        f"BulkSMSNigeria: Error {response.status_code}: {response.text}"
                    )
            except Exception as e:
                logger.error(f"BulkSMSNigeria: Delivery failed: {str(e)}")
        return count


class TermiiBackend(BaseSmsBackend):
    def send_messages(self, messages):
        from django.conf import settings

        api_key = settings.TERMII_API_KEY
        if not api_key or api_key.startswith("your_"):
            logger.warning("Termii: API Key not configured. Simulating success.")
            return len(messages)

        count = 0
        for msg in messages:
            try:
                payload = {
                    "api_key": api_key,
                    "to": msg.to[0],  # Termii usually takes single string
                    "from": msg.from_phone or "REPro",
                    "sms": msg.body,
                    "type": "plain",
                    "channel": "generic",
                }
                logger.info(f"Termii: Sending to {msg.to[0]}")
                response = requests.post(
                    "https://api.ng.termii.com/api/sms/send", json=payload, timeout=10
                )
                if response.status_code == 200:
                    count += 1
                    logger.info("Termii: Send successful.")
                else:
                    logger.error(
                        f"Termii: Error {response.status_code}: {response.text}"
                    )
            except Exception as e:
                logger.error(f"Termii: Delivery failed: {str(e)}")
        return count
