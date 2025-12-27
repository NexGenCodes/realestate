from rest_framework import viewsets, permissions, status
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db.models import Count, Q
from django.utils import timezone
from datetime import timedelta
from users.models import User
from properties.models import Property, AnalyticsEvent


class AdminDashboardViewSet(viewsets.ViewSet):
    """
    Admin Dashboard for platform-wide statistics.
    Only accessible by Superusers or Admin Role.
    """

    permission_classes = [permissions.IsAdminUser]

    def list(self, request):
        """Get global platform statistics."""
        now = timezone.now()
        last_7_days = now - timedelta(days=7)
        last_30_days = now - timedelta(days=30)

        # 1. User Stats
        total_users = User.objects.count()
        new_users_week = User.objects.filter(date_joined__gte=last_7_days).count()

        # 2. Property Stats
        total_properties = Property.objects.count()
        active_properties = Property.objects.filter(
            status=Property.Status.AVAILABLE
        ).count()
        banned_properties = Property.objects.filter(
            status=Property.Status.BANNED
        ).count()
        properties_added_week = Property.objects.filter(
            created_at__gte=last_7_days
        ).count()

        # 3. Revenue (Mock logic: $10 per listing)
        total_revenue = total_properties * 10
        revenue_week = properties_added_week * 10

        # 4. Recent Analytic Activity (Global)
        total_views_30d = AnalyticsEvent.objects.filter(
            event_type=AnalyticsEvent.EventType.VIEW, created_at__gte=last_30_days
        ).count()

        data = {
            "users": {
                "total": total_users,
                "new_this_week": new_users_week,
            },
            "properties": {
                "total": total_properties,
                "active": active_properties,
                "banned": banned_properties,
                "new_this_week": properties_added_week,
            },
            "financials": {
                "total_revenue": total_revenue,
                "revenue_this_week": revenue_week,
                "currency": "USD",
            },
            "engagement": {
                "total_views_30d": total_views_30d,
            },
        }

        return Response(data)

    @action(detail=False, methods=["get"])
    def recent_activity(self, request):
        """Get recent signups and listings."""
        recent_users = User.objects.order_by("-date_joined")[:5].values(
            "id", "email", "first_name", "last_name", "date_joined"
        )
        recent_properties = Property.objects.order_by("-created_at")[:5].values(
            "id", "title", "status", "created_at", "owner__email"
        )

        return Response(
            {"recent_users": recent_users, "recent_properties": recent_properties}
        )
