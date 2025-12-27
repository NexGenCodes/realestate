import logging
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.utils import timezone
from shared.security import sanitize_html
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator

logger = logging.getLogger(__name__)


class Amenity(models.Model):
    name = models.CharField(max_length=100)
    icon = models.CharField(max_length=50, blank=True, help_text="Frontend icon name")

    class Meta:
        verbose_name_plural = "Amenities"

    def __str__(self):
        return self.name


class Property(models.Model):
    class Status(models.TextChoices):
        AVAILABLE = "AVAILABLE", _("Available")
        RENTED = "RENTED", _("Rented")
        SOLD = "SOLD", _("Sold")
        BANNED = "BANNED", _("Banned")

    class Type(models.TextChoices):
        RENT = "RENT", _("For Rent")
        SALE = "SALE", _("For Sale")

    class AppealStatus(models.TextChoices):
        NONE = "NONE", _("No Appeal")
        PENDING = "PENDING", _("Appeal Pending")
        RESOLVED = "RESOLVED", _("Appeal Resolved")

    class Category(models.TextChoices):
        HOUSE = "HOUSE", _("House")
        SHOP = "SHOP", _("Shop")
        LAND = "LAND", _("Land")
        APARTMENT = "APARTMENT", _("Apartment")

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="properties"
    )
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.HOUSE
    )
    title = models.CharField(max_length=255)
    description = models.TextField()

    # Geo-spatial location (PostGIS PointField)
    location = models.PointField(srid=4326, null=True, blank=True)
    # Keeping latitude/longitude as legacy fields for backwards compatibility with existing frontend logic
    # but primarily using 'location' for spatial queries.
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    address_text = models.CharField(max_length=500)

    # Administrative Data (Auto-filled via Reverse Geocoding)
    city = models.CharField(max_length=100, blank=True, db_index=True)
    state = models.CharField(max_length=100, blank=True, db_index=True)
    country = models.CharField(max_length=100, blank=True, db_index=True)

    price = models.DecimalField(max_digits=15, decimal_places=2, db_index=True)
    property_type = models.CharField(
        max_length=10, choices=Type.choices, default=Type.SALE
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.AVAILABLE, db_index=True
    )

    # Common features
    bedrooms = models.PositiveIntegerField(default=0)
    bathrooms = models.PositiveIntegerField(default=0)
    area_sqft = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Area in square feet", default=0
    )
    amenities = models.ManyToManyField(Amenity, blank=True)
    video_url = models.URLField(max_length=500, blank=True, null=True)

    # Engagement Stats
    views_count = models.PositiveIntegerField(default=0, db_index=True)
    average_rating = models.DecimalField(
        max_digits=3, decimal_places=2, default=0.00, db_index=True
    )

    # Ban & Appeal
    is_banned = models.BooleanField(default=False)
    ban_reason = models.TextField(blank=True)
    appeal_status = models.CharField(
        max_length=10, choices=AppealStatus.choices, default=AppealStatus.NONE
    )
    appeal_text = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Properties"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "category"]),
            models.Index(fields=["status", "property_type"]),
            models.Index(fields=["owner", "status"]),
            # Composite indexes for common filters
            models.Index(fields=["status", "price"]),
            models.Index(fields=["status", "category", "price"]),
            models.Index(fields=["property_type", "price"]),
            models.Index(fields=["is_banned", "status"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        if self.description:
            self.description = sanitize_html(self.description)

        # Automatically sync latitude/longitude to the PostGIS PointField
        if self.latitude is not None and self.longitude is not None:
            new_location = Point(float(self.longitude), float(self.latitude))

            # Only geocode if location changed or fields are empty
            if self.location != new_location or not self.city:
                self.location = new_location
                self._reverse_geocode()
        elif self.location:
            # If location exists but lat/lon are missing, sync back
            self.latitude = self.location.y
            self.longitude = self.location.x

        # Handle status transitions
        if self.pk:
            old_instance = Property.objects.get(pk=self.pk)
            # If status changes to RENTED or SOLD, remove from favorites
            if old_instance.status == self.Status.AVAILABLE and self.status in [
                self.Status.RENTED,
                self.Status.SOLD,
            ]:
                logger.info(
                    f"Property {self.id} marked as {self.status}. Clearing favorites."
                )
                Favorite.objects.filter(property=self).delete()

        super().save(*args, **kwargs)

    def _reverse_geocode(self):
        """Helper to fetch city, state, country from coordinates."""
        from geopy.geocoders import Nominatim
        from geopy.exc import GeopyError

        try:
            geolocator = Nominatim(user_agent="realestate_app")
            location = geolocator.reverse(
                f"{self.latitude}, {self.longitude}", language="en"
            )
            if location and location.raw.get("address"):
                address = location.raw["address"]
                self.city = (
                    address.get("city")
                    or address.get("town")
                    or address.get("village")
                    or ""
                )
                self.state = address.get("state") or ""
                self.country = address.get("country") or ""
        except GeopyError as e:
            logger.warning(f"Reverse geocoding failed for property {self.id}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during geocoding: {e}")


class PropertyImage(models.Model):
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="images"
    )
    image_url = models.URLField(max_length=500)
    is_featured = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Image for {self.property.title}"


class Favorite(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="favorites"
    )
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="favorited_by"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "property")

    def __str__(self):
        return f"{self.user.email} favorited {self.property.title}"


class PropertyReview(models.Model):
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="reviews"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "property")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.rating} stars by {self.user.email}"


class TourRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")
        CANCELLED = "CANCELLED", _("Cancelled")

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="tour_requests"
    )
    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tour_requests"
    )
    slot = models.DateTimeField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Tour request for {self.property.title} by {self.requester.email}"


class PropertyReport(models.Model):
    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="reports"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="property_reports",
    )
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("user", "property")
        ordering = ["-created_at"]

    def __str__(self):
        return f"Report on {self.property.title} by {self.user.email}"


class AnalyticsEvent(models.Model):
    class EventType(models.TextChoices):
        VIEW = "VIEW", _("View")
        FAVORITE = "FAVORITE", _("Favorite")
        SHARE = "SHARE", _("Share")
        CONTACT = "CONTACT", _("Contact")

    property = models.ForeignKey(
        Property, on_delete=models.CASCADE, related_name="analytics_events"
    )
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="analytics_events",
    )
    # Generic info for anonymous users (e.g. session id / ip hash) - omitting for compliance simplicity
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["property", "event_type", "created_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} on {self.property.title} at {self.created_at}"
