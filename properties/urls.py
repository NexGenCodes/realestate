from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PropertyViewSet, PropertyAdminViewSet

router = DefaultRouter()
router.register(r"properties", PropertyViewSet, basename="property")
router.register(r"admin", PropertyAdminViewSet, basename="property-admin")

urlpatterns = [
    path("", include(router.urls)),
]
