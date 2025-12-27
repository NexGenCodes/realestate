from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils.translation import gettext_lazy as _
from .models import User, OwnerRequest


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    # The forms to add and change user instances
    # form = UserChangeForm
    # add_form = UserCreationForm

    # The fields to be used in displaying the User model.
    # These override the definitions on the base UserAdmin
    # that reference username.
    ordering = ["email"]
    list_display = ["email", "first_name", "last_name", "is_staff", "role"]
    search_fields = ["email", "first_name", "last_name"]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            _("Personal info"),
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "country",
                    "gender",
                    "phone_number",
                    "bio",
                    "profile_picture_url",
                )
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
        (_("Role"), {"fields": ("role",)}),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password", "confirm_password"),
            },
        ),
    )


@admin.register(OwnerRequest)
class OwnerRequestAdmin(admin.ModelAdmin):
    list_display = ("user", "status", "is_verified", "created_at")
    list_filter = ("status", "is_verified")
    actions = ["approve_request", "reject_request"]

    def approve_request(self, request, queryset):
        queryset.update(status="APPROVED", is_verified=True)
        # Upgrade user roles
        for req in queryset:
            req.user.role = User.Role.OWNER
            req.user.save()

    approve_request.short_description = "Approve selected owner requests"

    def reject_request(self, request, queryset):
        queryset.update(status="REJECTED")

    reject_request.short_description = "Reject selected owner requests"
