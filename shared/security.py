import bleach
import logging
from rest_framework.throttling import UserRateThrottle

logger = logging.getLogger(__name__)

# Sanitization Configuration
ALLOWED_TAGS = [
    "p",
    "b",
    "i",
    "u",
    "em",
    "strong",
    "a",
    "ul",
    "ol",
    "li",
    "br",
    "h1",
    "h2",
    "h3",
]
ALLOWED_ATTRIBUTES = {
    "a": ["href", "title", "target", "rel"],
}


def sanitize_html(html_content: str) -> str:
    """
    Sanitizes HTML content by stripping unsafe tags and attributes.
    Useful for property descriptions and user comments.
    """
    if not html_content:
        return ""
    return bleach.clean(
        html_content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES, strip=True
    )


class BurstRateThrottle(UserRateThrottle):
    """
    Custom throttle to handle short bursts of requests.
    Useful for protecting sensitive actions like messaging.
    """

    scope = "burst"

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            ident = request.user.pk
        else:
            ident = self.get_ident(request)
        return self.cache_format % {"scope": self.scope, "ident": ident}
