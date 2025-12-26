import logging
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

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

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    profile_picture_url = models.URLField(max_length=500, null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    gender = models.CharField(
        max_length=10, choices=Gender.choices, null=True, blank=True
    )
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)

    # Overriding to make email unique
    email = models.EmailField(_("email address"), unique=True)

    def __str__(self):
        return self.username

    def save(self, *args, **kwargs):
        if not self.id:
            logger.info(f"Creating new user: {self.username}")
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
        return f"{self.user.username} - {self.status}"

    def save(self, *args, **kwargs):
        if not self.id:
            logger.info(f"New owner request submitted by user: {self.user.username}")
        super().save(*args, **kwargs)
