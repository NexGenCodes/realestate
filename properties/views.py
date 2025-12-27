import logging
from django.db import transaction, models
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework_gis.filters import DistanceToPointFilter

from .models import Property, Favorite, Amenity, PropertyReview, TourRequest
from .serializers import (
    PropertySerializer,
    FavoriteSerializer,
    AmenitySerializer,
    PropertyReviewSerializer,
    TourRequestSerializer,
)
from .filters import PropertyFilter
from .permissions import IsOwnerRole, IsOwnerOrReadOnly
from users.models import User
from django.db.models import Avg
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from shared.messaging import (
    notify_owner_property_status_change,
    check_email_credits,
    notify_owner_new_tour_request,
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
        DistanceToPointFilter,
    ]
    filterset_class = PropertyFilter
    search_fields = ["title", "description", "address_text"]
    ordering_fields = ["price", "created_at", "average_rating", "views_count"]
    distance_filter_field = "location"
    distance_filter_convert_meters = True

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
        favorite, created = Favorite.objects.get_or_create(
            user=request.user, property=property_obj
        )

        if not created:
            favorite.delete()
            logger.info(
                f"User {request.user.email} removed property {pk} from favorites."
            )
            return Response(
                {"message": "Removed from favorites."}, status=status.HTTP_200_OK
            )

        logger.info(f"User {request.user.email} added property {pk} to favorites.")
        return Response(
            {"message": "Added to favorites."}, status=status.HTTP_201_CREATED
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
        if property_obj.status != Property.Status.AVAILABLE:
            return Response(
                {"error": "Only available properties can be marked as rented."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        property_obj.status = Property.Status.RENTED
        property_obj.save()  # This clears favorites automated via model save()

        logger.info(f"Property {pk} marked as RENTED by user {request.user.email}.")

        notify_owner_property_status_change(
            property_obj.owner.email, property_obj.title, "RENTED"
        )
        check_email_credits()

        return Response(
            {"message": "Property marked as rented. Owner notified."},
            status=status.HTTP_200_OK,
        )

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
        if property_obj.status != Property.Status.AVAILABLE:
            return Response(
                {"error": "Only available properties can be marked as sold."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        property_obj.status = Property.Status.SOLD
        property_obj.save()  # This clears favorites automated via model save()

        logger.info(f"Property {pk} marked as SOLD by user {request.user.email}.")

        notify_owner_property_status_change(
            property_obj.owner.email, property_obj.title, "SOLD"
        )
        check_email_credits()

        return Response(
            {"message": "Property marked as sold. Owner notified."},
            status=status.HTTP_200_OK,
        )

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
        property_obj.is_banned = True
        property_obj.ban_reason = reason
        property_obj.status = Property.Status.BANNED
        property_obj.save()

        logger.warning(
            f"Admin {request.user.email} BANNED property {pk}. Reason: {reason}"
        )

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
        if not property_obj.is_banned:
            return Response(
                {"error": "Only banned properties can be appealed."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        appeal_text = request.data.get("appeal_text")
        if not appeal_text:
            return Response(
                {"error": "Appeal text is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        property_obj.appeal_status = Property.AppealStatus.PENDING
        property_obj.appeal_text = appeal_text
        property_obj.save()

        logger.info(
            f"Owner {request.user.email} submitted an APPEAL for property {pk}."
        )

        return Response(
            {"message": "Appeal submitted for admin review."}, status=status.HTTP_200_OK
        )

    @swagger_auto_schema(
        operation_summary="Lift ban",
        operation_description="Admin only: Remove a ban from a property listing.",
        responses={200: "Ban lifted"},
    )
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAdminUser])
    def lift_ban(self, request, pk=None):
        """Admin only: Lift a ban on a property listing."""
        property_obj = self.get_object()
        property_obj.is_banned = False
        property_obj.status = Property.Status.AVAILABLE
        property_obj.appeal_status = Property.AppealStatus.RESOLVED
        property_obj.save()

        logger.info(f"Admin {request.user.email} LIFTED BAN on property {pk}.")

        return Response(
            {"message": "Ban lifted. Property is now available."},
            status=status.HTTP_200_OK,
        )


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
        property_obj.is_banned = True
        property_obj.ban_reason = reason
        property_obj.status = Property.Status.BANNED
        property_obj.save()

        logger.warning(
            f"Admin {request.user.email} BANNED property {pk}. Reason: {reason}"
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
        property_obj.is_banned = False
        property_obj.status = Property.Status.AVAILABLE
        property_obj.appeal_status = Property.AppealStatus.RESOLVED
        property_obj.save()

        logger.info(f"Admin {request.user.email} LIFTED BAN on property {pk}.")

        return Response(
            {"message": "Ban lifted. Property is now available."},
            status=status.HTTP_200_OK,
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

    @transaction.atomic
    def perform_create(self, serializer):
        review = serializer.save(user=self.request.user)
        # Update property average rating
        prop = review.property
        avg_rating = PropertyReview.objects.filter(property=prop).aggregate(
            Avg("rating")
        )["rating__avg"]
        prop.average_rating = avg_rating or 0
        prop.save()

        # Notify Owner
        from users.models import Notification

        Notification.objects.create(
            user=prop.owner,
            title="New Review",
            body=f"{self.request.user.email} reviewed your property '{prop.title}'.",
        )

        logger.info(f"User {self.request.user.email} reviewed property {prop.id}")


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
        instance = serializer.save(requester=self.request.user)

        # Notify Owner (In-app + Email)
        notify_owner_new_tour_request(
            owner_email=instance.property.owner.email,
            property_title=instance.property.title,
            requester_email=self.request.user.email,
            slot=instance.slot,
        )

        logger.info(
            f"[TOUR_REQUEST] User {self.request.user.email} requested a tour for property {instance.property.id}"
        )

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrReadOnly])
    def approve(self, request, pk=None):
        tour = self.get_object()
        tour.status = TourRequest.Status.APPROVED
        tour.save()
        return Response({"status": "Tour request approved"})

    @action(detail=True, methods=["post"], permission_classes=[IsOwnerOrReadOnly])
    def reject(self, request, pk=None):
        tour = self.get_object()
        tour.status = TourRequest.Status.REJECTED
        tour.save()
        return Response({"status": "Tour request rejected"})


class OwnerAnalyticsView(APIView):
    """Owner dashboard analytics endpoint."""

    permission_classes = [permissions.IsAuthenticated, IsOwnerRole]

    def get(self, request):
        user = request.user
        owner_properties = Property.objects.filter(owner=user)

        total_views = owner_properties.aggregate(models.Sum("views_count"))[
            "views_count__sum"
        ]
        total_favorites = Favorite.objects.filter(property__owner=user).count()
        total_tours = TourRequest.objects.filter(property__owner=user).count()

        return Response(
            {
                "total_properties": owner_properties.count(),
                "total_views": total_views or 0,
                "total_favorites": total_favorites,
                "total_tour_requests": total_tours,
            }
        )
