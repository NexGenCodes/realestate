import logging
from django.contrib.gis.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


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

    # Geo-spatial location
    location = models.PointField(srid=4326)
    address_text = models.CharField(max_length=500)

    price = models.DecimalField(max_digits=15, decimal_places=2)
    property_type = models.CharField(
        max_length=10, choices=Type.choices, default=Type.SALE
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.AVAILABLE
    )

    # Common features
    bedrooms = models.PositiveIntegerField(default=0)
    bathrooms = models.PositiveIntegerField(default=0)
    area_sqft = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Area in square feet", default=0
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

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    def save(self, *args, **kwargs):
        # Auto-ban check logic could go here if needed
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
                # Notification logic will be triggered in the View/Serializer level for easier task offloading

        super().save(*args, **kwargs)


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
        return f"{self.user.username} favorited {self.property.title}"
