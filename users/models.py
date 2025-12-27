import logging
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from .managers import CustomUserManager

logger = logging.getLogger(__name__)


class User(AbstractUser):
    class Role(models.TextChoices):
        USER = "USER", _("User")
        OWNER = "OWNER", _("Owner")
        ADMIN = "ADMIN", _("Admin")

    class Gender(models.TextChoices):
        MALE = "MALE", _("Male")
        FEMALE = "FEMALE", _("Female")
        OTHER = "OTHER", _("Other")

    username = None  # Removed username field
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    profile_picture_url = models.URLField(max_length=500, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    gender = models.CharField(
        max_length=10, choices=Gender.choices, null=True, blank=True
    )
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    is_verified_owner = models.BooleanField(default=False)

    # Overriding to make email unique
    email = models.EmailField(_("email address"), unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = CustomUserManager()

    def __str__(self):
        return self.email

    def save(self, *args, **kwargs):
        if not self.id:
            logger.info(f"Creating new user: {self.email}")
        super().save(*args, **kwargs)


class OwnerRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        APPROVED = "APPROVED", _("Approved")
        REJECTED = "REJECTED", _("Rejected")

    class IdType(models.TextChoices):
        DRIVERS_LICENSE = "DRIVERS_LICENSE", _("Driver's License")
        NATIONAL_ID = "NATIONAL_ID", _("National ID")
        PASSPORT = "PASSPORT", _("Passport")
        VOTERS_CARD = "VOTERS_CARD", _("Voter's Card")

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="owner_requests"
    )
    id_type = models.CharField(
        max_length=20, choices=IdType.choices, default=IdType.NATIONAL_ID
    )
    documents_url = models.URLField(max_length=500, null=True, blank=True)
    reason = models.TextField(
        help_text="Reason for requesting owner status", default=""
    )
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PENDING
    )
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.email} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.id:
            logger.info(f"New owner request submitted by user: {self.user.email}")
        super().save(*args, **kwargs)


class SavedSearch(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="saved_searches"
    )
    name = models.CharField(max_length=100)
    filters = models.JSONField(default=dict)
    notification_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} ({self.user.email})"


class DeviceToken(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="device_tokens"
    )
    token = models.CharField(max_length=255, unique=True)
    platform = models.CharField(max_length=20)  # e.g., ios, android, web
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} - {self.platform}"


class Notification(models.Model):
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="notifications"
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Notification for {self.user.email}: {self.title}"
