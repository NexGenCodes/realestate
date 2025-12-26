import logging
from django.db import transaction
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework_gis.filters import DistanceToPointFilter

from .models import Property, Favorite
from .serializers import PropertySerializer, FavoriteSerializer
from .permissions import IsOwnerRole, IsOwnerOrReadOnly
from users.models import User
from django.utils.decorators import method_decorator
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from shared.messaging import notify_owner_property_status_change, check_email_credits

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
    filterset_fields = ["category", "property_type", "status", "bedrooms", "bathrooms"]
    search_fields = ["title", "description", "address_text"]
    ordering_fields = ["price", "created_at"]
    distance_filter_field = "location"
    distance_filter_convert_meters = True

    def get_permissions(self):
        if self.action in ["list", "retrieve"]:
            return [permissions.AllowAny()]
        if self.action == "create":
            return [permissions.IsAuthenticated(), IsOwnerRole()]
        return [permissions.IsAuthenticated(), IsOwnerOrReadOnly()]

    def get_queryset(self):
        qs = super().get_queryset().prefetch_related("images", "owner", "category")

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
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Create property",
        operation_description="Create a new property listing. Requires 3-5 images.",
    )
    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
        logger.info(
            f"User {self.request.user.username} created a new property listing."
        )

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
                f"User {request.user.username} removed property {pk} from favorites."
            )
            return Response(
                {"message": "Removed from favorites."}, status=status.HTTP_200_OK
            )

        logger.info(f"User {request.user.username} added property {pk} to favorites.")
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

        logger.info(f"Property {pk} marked as RENTED by user {request.user.username}.")

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

        logger.info(f"Property {pk} marked as SOLD by user {request.user.username}.")

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
        manual_parameters=[
            openapi.Parameter(
                "reason",
                openapi.IN_BODY,
                type=openapi.TYPE_STRING,
                description="Reason for the ban",
            )
        ],
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
            f"Admin {request.user.username} BANNED property {pk}. Reason: {reason}"
        )

        return Response(
            {"message": f"Property banned. Reason: {reason}"}, status=status.HTTP_200_OK
        )

    @swagger_auto_schema(
        operation_summary="Appeal ban",
        manual_parameters=[
            openapi.Parameter(
                "appeal_text",
                openapi.IN_BODY,
                type=openapi.TYPE_STRING,
                description="Grounds for appeal",
            )
        ],
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
            f"Owner {request.user.username} submitted an APPEAL for property {pk}."
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

        logger.info(f"Admin {request.user.username} LIFTED BAN on property {pk}.")

        return Response(
            {"message": "Ban lifted. Property is now available."},
            status=status.HTTP_200_OK,
        )


class FavoriteViewSet(viewsets.ModelViewSet):
    """ViewSet for users to manage their favorite properties."""

    serializer_class = FavoriteSerializer
    permission_classes = [permissions.IsAuthenticated]

    @swagger_auto_schema(
        operation_summary="List favorites",
        operation_description="Retrieve a list of properties favorited by the current user.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        return Favorite.objects.filter(user=self.request.user).select_related(
            "property"
        )

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
    search_fields = ["title", "description", "address_text", "owner__username"]
    ordering_fields = ["price", "created_at", "status"]

    @swagger_auto_schema(
        operation_summary="List all properties (Admin)",
        operation_description="Admin view of all properties including banned and sold listings.",
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @swagger_auto_schema(
        operation_summary="Ban property (Admin)",
        manual_parameters=[
            openapi.Parameter(
                "reason",
                openapi.IN_BODY,
                type=openapi.TYPE_STRING,
                description="Reason for the ban",
            )
        ],
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
            f"Admin {request.user.username} BANNED property {pk}. Reason: {reason}"
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

        logger.info(f"Admin {request.user.username} LIFTED BAN on property {pk}.")

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
