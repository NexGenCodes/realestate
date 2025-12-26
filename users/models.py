from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

class User(AbstractUser):
    class Role(models.TextChoices):
        USER = 'USER', _('User')
        OWNER = 'OWNER', _('Owner')
        ADMIN = 'ADMIN', _('Admin')

    class Gender(models.TextChoices):
        MALE = 'MALE', _('Male')
        FEMALE = 'FEMALE', _('Female')
        OTHER = 'OTHER', _('Other')

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.USER)
    profile_picture = models.ImageField(upload_to='profile_pics/', null=True, blank=True)
    country = models.CharField(max_length=100, null=True, blank=True)
    gender = models.CharField(max_length=10, choices=Gender.choices, null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    
    # Overriding to make email unique
    email = models.EmailField(_('email address'), unique=True)

    def __str__(self):
        return self.username

class OwnerRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', _('Pending')
        APPROVED = 'APPROVED', _('Approved')
        REJECTED = 'REJECTED', _('Rejected')

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owner_requests')
    documents = models.FileField(upload_to='owner_documents/')
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    is_phone_verified = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.username} - {self.status}"
