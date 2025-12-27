import logging
from django.db import transaction, models
from django.utils import timezone
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend

from .models import (
    Property,
    Favorite,
    Amenity,
    PropertyReview,
    TourRequest,
    PropertyReport,
)
from .serializers import (
    PropertySerializer,
    FavoriteSerializer,
    AmenitySerializer,
    PropertyReviewSerializer,
    TourRequestSerializer,
    PropertyReportSerializer,
)
from .filters import PropertyFilter
from .permissions import IsOwnerRole, IsOwnerOrReadOnly
from users.models import User
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from shared.security import BurstRateThrottle
from shared.webhooks import trigger_event
from .reports import generate_analytics_pdf
from .services import (
    PropertyService,
    ReportingService,
    ReviewService,
    TourRequestService,
)

logger = logging.getLogger(__name__)


class HealthCheckView(APIView):
    """Simple health check endpoint."""

    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({"status": "healthy"}, status=status.HTTP_200_OK)


class PropertyViewSet(viewsets.ModelViewSet):
    """
    ViewSet for viewing and editing property listings.
    Supports PostGIS spatial filtering and status management.
    """

    queryset = Property.objects.all()
    serializer_class = PropertySerializer
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = PropertyFilter
    search_fields = ["title", "description", "address_text", "owner__email"]
    ordering_fields = ["price", "created_at", "average_rating", "views_count"]
    permission_classes = [IsOwnerOrReadOnly]
    throttle_classes = [BurstRateThrottle]

    def get_throttles(self):
        if self.action == "create":
            self.throttle_scope = "property_create"
        return super().get_throttles()

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        if self.action == "create":
            return [permissions.IsAuthenticated(), IsOwnerRole()]
        if self.action == "toggle_favorite":
            return [permissions.IsAuthenticated()]
        return [permissions.IsAuthenticated(), IsOwnerOrReadOnly()]

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related("images", "owner")

        # Regular users can only see available (not banned, not rented, not sold)
        if (
            not self.request.user.is_authenticated
            or self.request.user.role == User.Role.USER
        ):
            return qs.filter(status=Property.Status.AVAILABLE, is_banned=False)

        # Owners can see their own properties regardless of status
        if self.request.user.role == User.Role.OWNER:
            return qs.filter(
                models.Q(owner=self.request.user)
                | models.Q(status=Property.Status.AVAILABLE, is_banned=False)
            )

        # Admins see everything
        return qs

    @swagger_auto_schema(
        operation_summary="List properties",
        operation_description="Retrieve a list of available properties. Supports filtering by category, price, and location.",
    )
    @method_decorator(cache_page(60 * 5))  # Cache for 5 minutes
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Retrieve property",
        operation_description="Get detailed information about a property, including amenities and reviews. Increments view count.",
    )
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        # Increment view count
        Property.objects.filter(pk=instance.pk).update(
            views_count=models.F("views_count") + 1
        )
        return super().retrieve(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Similar properties",
        operation_description="Get properties similar to the current one based on category and price range.",
    )
    @action(detail=True, methods=["get"])
    def similar_properties(self, request, pk=None):
        """Recommendation engine: Same category, similar price range."""
        instance = self.get_object()
        price = float(instance.price)
        qs = (
            Property.objects.filter(
                category=instance.category,
                status=Property.Status.AVAILABLE,
                is_banned=False,
                price__gte=price * 0.8,
                price__lte=price * 1.2,
            )
            .exclude(pk=instance.pk)
            .order_by("-average_rating")[:5]
        )

        serializer = self.get_serializer(qs, many=True)
        logger.info(f"[PROPERTY] Found {len(qs)} similar properties for property {pk}")
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_summary="Create property",
        operation_description="Create a new property listing. Requires 3-5 images.",
    )
    def perform_create(self, serializer):
        # Clear list cache
        cache.delete_pattern("views.decorators.cache.cache_page.*properties*")
        serializer.save(owner=self.request.user)
        logger.info(f"User {self.request.user.email} created a new property listing.")

    def perform_update(self, serializer):
        cache.delete_pattern("views.decorators.cache.cache_page.*properties*")
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        cache.delete_pattern("views.decorators.cache.cache_page.*properties*")
        super().perform_destroy(instance)

    @swagger_auto_schema(
        operation_summary="Toggle favorite",
        operation_description="Add or remove the property from the user's favorites list.",
        responses={201: "Added to favorites", 200: "Removed from favorites"},
    )
    @transaction.atomic
    @action(
        detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def toggle_favorite(self, request, pk=None):
        """Toggle favorite status for the authenticated user."""
        property_obj = self.get_object()
        added = PropertyService.toggle_favorite(property_obj, request.user)

        if added:
            return Response(
                {"message": "Added to favorites."}, status=status.HTTP_201_CREATED
            )
        else:
            return Response(
                {"message": "Removed from favorites."}, status=status.HTTP_200_OK
            )

    @swagger_auto_schema(
        operation_summary="Mark as rented",
        operation_description="Change property status to RENTED and notify the owner via email.",
        responses={200: "Status updated", 400: "Invalid status transition"},
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated, IsOwnerOrReadOnly],
    )
    def mark_as_rented(self, request, pk=None):
        """Mark property as rented and notify owner."""
        property_obj = self.get_object()
        try:
            PropertyService.mark_as_rented(property_obj, request.user)
            return Response(
                {"message": "Property marked as rented. Owner notified."},
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        operation_summary="Mark as sold",
        operation_description="Change property status to SOLD and notify the owner via email.",
        responses={200: "Status updated", 400: "Invalid status transition"},
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated, IsOwnerOrReadOnly],
    )
    def mark_as_sold(self, request, pk=None):
        """Mark property as sold and notify owner."""
        property_obj = self.get_object()
        try:
            PropertyService.mark_as_sold(property_obj, request.user)
            return Response(
                {"message": "Property marked as sold. Owner notified."},
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        operation_summary="Ban property",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "reason": openapi.Schema(
                    type=openapi.TYPE_STRING, description="Reason for the ban"
                )
            },
            required=["reason"],
        ),
        responses={200: "Property banned"},
    )
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def ban(self, request, pk=None):
        """Admin only: Ban a property listing."""
        property_obj = self.get_object()
        reason = request.data.get("reason", "No reason provided.")
        PropertyService.ban_property(property_obj, reason, request.user)
        return Response(
            {"message": f"Property banned. Reason: {reason}"}, status=status.HTTP_200_OK
        )

    @swagger_auto_schema(
        operation_summary="Appeal ban",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "appeal_text": openapi.Schema(
                    type=openapi.TYPE_STRING, description="Grounds for appeal"
                )
            },
            required=["appeal_text"],
        ),
        responses={200: "Appeal submitted"},
    )
    @action(
        detail=True,
        methods=["post"],
        permission_classes=[permissions.IsAuthenticated, IsOwnerOrReadOnly],
    )
    def appeal(self, request, pk=None):
        """Owner only: Appeal a banned property listing."""
        property_obj = self.get_object()
        appeal_text = request.data.get("appeal_text")
        if not appeal_text:
            return Response(
                {"error": "Appeal text is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            PropertyService.appeal_ban(property_obj, appeal_text, request.user)
            return Response(
                {"message": "Appeal submitted for admin review."},
                status=status.HTTP_200_OK,
            )
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        operation_summary="Lift ban",
        operation_description="Admin only: Remove a ban from a property listing.",
        responses={200: "Ban lifted"},
    )
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def lift_ban(self, request, pk=None):
        """Admin only: Lift a ban on a property listing."""
        property_obj = self.get_object()
        PropertyService.lift_ban(property_obj, request.user)
        return Response(
            {"message": "Ban lifted. Property is now available."},
            status=status.HTTP_200_OK,
        )

    @swagger_auto_schema(
        operation_summary="Report property",
        request_body=PropertyReportSerializer,
        responses={201: "Property reported", 400: "Invalid report"},
    )
    @action(
        detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated]
    )
    def report(self, request, pk=None):
        """Allow users to report a property. Automatic ban at 5 reports."""
        property_obj = self.get_object()
        reason = request.data.get("reason", "No reason provided.")

        try:
            report_obj = ReportingService.report_property(
                property_obj, request.user, reason
            )
            serializer = PropertyReportSerializer(report_obj)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class FavoriteViewSet(viewsets.ModelViewSet):
    """ViewSet for users to manage their favorite properties."""

    serializer_class = FavoriteSerializer

    def get_permissions(self):
        return [permissions.IsAuthenticated()]

    @swagger_auto_schema(
        operation_summary="List favorites",
        operation_description="Admin/Owner only: Retrieve a list of properties favorited by the current user.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        if (
            getattr(self, "swagger_fake_view", False)
            or not self.request.user.is_authenticated
        ):
            return Favorite.objects.none()

        user = self.request.user
        if user.role == User.Role.ADMIN:
            return Favorite.objects.all().select_related("property")

        # Owners and Regular users can list their own favorites
        return Favorite.objects.filter(user=user).select_related("property")

    @swagger_auto_schema(
        operation_summary="Add favorite",
        operation_description="Add a property to the user's favorites list.",
    )
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @swagger_auto_schema(
        operation_summary="Remove favorite",
        operation_description="Remove a property from the user's favorites list.",
    )
    def destroy(self, request, *args, **kwargs):
        return super().destroy(request, *args, **kwargs)


class PropertyAdminViewSet(viewsets.ReadOnlyModelViewSet):
    """Admin-only viewset for property management."""

    queryset = Property.objects.all()
    serializer_class = PropertySerializer
    permission_classes = [permissions.IsAdminUser]
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_fields = [
        "category",
        "property_type",
        "status",
        "bedrooms",
        "bathrooms",
        "is_banned",
    ]
    search_fields = ["title", "description", "address_text", "owner__email"]
    ordering_fields = ["price", "created_at", "status"]

    @swagger_auto_schema(
        operation_summary="List all properties (Admin)",
        operation_description="Admin view of all properties including banned and sold listings.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Ban property (Admin)",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "reason": openapi.Schema(
                    type=openapi.TYPE_STRING, description="Reason for the ban"
                )
            },
            required=["reason"],
        ),
        responses={200: "Property banned"},
    )
    @action(detail=True, methods=["post"])
    def ban(self, request, pk=None):
        """Admin only: Ban a property listing."""
        property_obj = self.get_object()
        reason = request.data.get("reason", "No reason provided.")
        PropertyService.ban_property(property_obj, reason, request.user)

        # Trigger webhook
        trigger_event(
            "property.banned",
            {
                "id": property_obj.id,
                "title": property_obj.title,
                "reason": reason,
            },
        )

        return Response(
            {"message": f"Property banned. Reason: {reason}"}, status=status.HTTP_200_OK
        )

    @swagger_auto_schema(
        operation_summary="Lift ban (Admin)",
        operation_description="Admin only: Remove a ban from a property listing.",
        responses={200: "Ban lifted"},
    )
    @action(detail=True, methods=["post"])
    def lift_ban(self, request, pk=None):
        """Admin only: Lift a ban on a property listing."""
        property_obj = self.get_object()
        PropertyService.lift_ban(property_obj, request.user)
        return Response(
            {"message": "Ban lifted. Property is now available."},
            status=status.HTTP_200_OK,
        )

    @swagger_auto_schema(
        operation_summary="Bulk status update (Admin)",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "property_ids": openapi.Schema(
                    type=openapi.TYPE_ARRAY,
                    items=openapi.Schema(type=openapi.TYPE_INTEGER),
                    description="List of property IDs",
                ),
                "action": openapi.Schema(
                    type=openapi.TYPE_STRING,
                    enum=["ban", "lift_ban"],
                    description="Action to perform",
                ),
                "reason": openapi.Schema(
                    type=openapi.TYPE_STRING, description="Reason (for banning)"
                ),
            },
            required=["property_ids", "action"],
        ),
        responses={200: "Bulk update completed"},
    )
    @action(detail=False, methods=["post"])
    def bulk_status_update(self, request):
        """Admin only: Bulk ban or lift ban on properties."""
        property_ids = request.data.get("property_ids", [])
        action_type = request.data.get("action")
        reason = request.data.get("reason", "Bulk action.")

        properties = Property.objects.filter(id__in=property_ids)

        if action_type == "ban":
            properties.update(
                is_banned=True,
                ban_reason=reason,
                status=Property.Status.BANNED,
                updated_at=timezone.now(),
            )
            logger.warning(
                f"Admin {request.user.email} bulk BANNED properties: {property_ids}"
            )
        elif action_type == "lift_ban":
            properties.update(
                is_banned=False,
                status=Property.Status.AVAILABLE,
                appeal_status=Property.AppealStatus.RESOLVED,
                updated_at=timezone.now(),
            )
            logger.info(
                f"Admin {request.user.email} bulk LIFTED BAN on properties: {property_ids}"
            )
        else:
            return Response(
                {"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {
                "message": f"Bulk {action_type} completed for {properties.count()} properties."
            }
        )

    @swagger_auto_schema(
        operation_summary="Review appeals (Admin)",
        operation_description="List all properties with pending appeals.",
    )
    @action(detail=False, methods=["get"])
    def pending_appeals(self, request):
        """Admin only: List properties with pending appeals."""
        appeals = Property.objects.filter(
            appeal_status=Property.AppealStatus.PENDING
        ).select_related("owner")

        serializer = self.get_serializer(appeals, many=True)
        return Response(serializer.data)


class AmenityViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for listing available amenities."""

    queryset = Amenity.objects.all()
    serializer_class = AmenitySerializer
    permission_classes = [permissions.AllowAny]


class PropertyReviewViewSet(viewsets.ModelViewSet):
    """ViewSet for property reviews."""

    serializer_class = PropertyReviewSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return PropertyReview.objects.none()
        property_id = self.request.query_params.get("property")
        if property_id:
            return PropertyReview.objects.filter(property_id=property_id)
        return PropertyReview.objects.all()

    def perform_create(self, serializer):
        ReviewService.create_review(
            property_obj=serializer.validated_data["property"],
            user=self.request.user,
            rating=serializer.validated_data["rating"],
            comment=serializer.validated_data.get("comment", ""),
        )


class TourRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for managing tour requests."""

    serializer_class = TourRequestSerializer

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.IsAuthenticated(), IsOwnerRole()]
        return [permissions.IsAuthenticated()]

    def get_queryset(self):
        if (
            getattr(self, "swagger_fake_view", False)
            or not self.request.user.is_authenticated
        ):
            return TourRequest.objects.none()
        user = self.request.user
        if user.role == User.Role.ADMIN:
            return TourRequest.objects.all()
        # Owners see requests for their properties, Users see their own requests
        return TourRequest.objects.filter(
            models.Q(requester=user) | models.Q(property__owner=user)
        )

    def perform_create(self, serializer):
        TourRequestService.create_tour_request(
            property_obj=serializer.validated_data["property"],
            requester=self.request.user,
            slot=serializer.validated_data["slot"],
            message=serializer.validated_data.get("message", ""),
        )

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrReadOnly])
    def approve(self, request, pk=None):
        tour = self.get_object()
        TourRequestService.update_status(
            tour, TourRequest.Status.APPROVED, request.user
        )
        return Response({"status": "Tour request approved"})

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrReadOnly])
    def reject(self, request, pk=None):
        tour = self.get_object()
        TourRequestService.update_status(
            tour, TourRequest.Status.REJECTED, request.user
        )
        return Response({"status": "Tour request rejected"})


class OwnerAnalyticsViewSet(viewsets.ViewSet):
    """Owner dashboard analytics ViewSet."""

    permission_classes = [permissions.IsAuthenticated, IsOwnerRole]

    def list(self, request):
        user = request.user
        cache_key = f"owner_analytics_{user.id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)

        owner_properties = Property.objects.filter(owner=user)

        total_views = owner_properties.aggregate(models.Sum("views_count"))[
            "views_count__sum"
        ]
        total_favorites = Favorite.objects.filter(property__owner=user).count()
        total_tours = TourRequest.objects.filter(property__owner=user).count()

        data = {
            "total_properties": owner_properties.count(),
            "total_views": total_views or 0,
            "total_favorites": total_favorites,
            "total_tour_requests": total_tours,
        }
        cache.set(cache_key, data, timeout=300)  # 5 minute cache
        return Response(data)

    @action(detail=False, methods=["get"], url_path="export-report")
    def export_report(self, request):
        from django.http import HttpResponse
        from django.utils import timezone

        user = request.user
        # Get data (re-using logic or cache)
        owner_properties = Property.objects.filter(owner=user)
        total_views = owner_properties.aggregate(models.Sum("views_count"))[
            "views_count__sum"
        ]
        total_favorites = Favorite.objects.filter(property__owner=user).count()
        total_tours = TourRequest.objects.filter(property__owner=user).count()

        data = {
            "total_properties": owner_properties.count(),
            "total_views": total_views or 0,
            "total_favorites": total_favorites,
            "total_tour_requests": total_tours,
            "generated_at": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        pdf_content = generate_analytics_pdf(data, user.email)

        logger.info(f"[ANALYTICS] PDF report generated for owner {user.email}")

        response = HttpResponse(pdf_content, content_type="application/pdf")
        response["Content-Disposition"] = f'attachment; filename="analytics_report.pdf"'
        return response
