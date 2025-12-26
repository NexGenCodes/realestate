from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, OwnerRequest

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        (None, {'fields': ('role', 'profile_picture')}),
    )
    list_display = UserAdmin.list_display + ('role',)
    list_filter = UserAdmin.list_filter + ('role',)

@admin.register(OwnerRequest)
class OwnerRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'status', 'is_verified', 'created_at')
    list_filter = ('status', 'is_verified')
    actions = ['approve_request', 'reject_request']

    def approve_request(self, request, queryset):
        queryset.update(status='APPROVED', is_verified=True)
        # Upgrade user roles
        for req in queryset:
            req.user.role = User.Role.OWNER
            req.user.save()
    approve_request.short_description = "Approve selected owner requests"

    def reject_request(self, request, queryset):
        queryset.update(status='REJECTED')
    reject_request.short_description = "Reject selected owner requests"
