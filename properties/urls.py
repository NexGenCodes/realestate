from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    PropertyViewSet,
    PropertyAdminViewSet,
    AmenityViewSet,
    PropertyReviewViewSet,
    TourRequestViewSet,
    OwnerAnalyticsView,
)

router = DefaultRouter()
router.register(r"admin", PropertyAdminViewSet, basename="property-admin")
router.register(r"amenities", AmenityViewSet, basename="amenity")
router.register(r"reviews", PropertyReviewViewSet, basename="review")
router.register(r"tour-requests", TourRequestViewSet, basename="tour-request")
router.register(r"", PropertyViewSet, basename="property")

urlpatterns = [
    path("analytics/", OwnerAnalyticsView.as_view(), name="owner-analytics"),
    path("", include(router.urls)),
]
