import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.contrib.gis.geos import Point
from unittest.mock import patch
from .models import Property, Favorite, PropertyReview, TourRequest
from users.models import Notification

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def test_password():
    return "TemporaryPassword123!"


@pytest.fixture
def verified_owner(db, test_password):
    user = User.objects.create_user(
        email="owner@example.com",
        password=test_password,
        role=User.Role.OWNER,
        is_verified_owner=True,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.fixture
def regular_user(db, test_password):
    user = User.objects.create_user(email="regular@example.com", password=test_password)
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.mark.django_db
class TestPropertiesApp:

    def test_property_lifecycle(self, verified_owner):
        user, client = verified_owner

        # 1. Create Property
        res = client.post(
            reverse("property-list"),
            {
                "title": "Pro Villa",
                "description": "Luxurious apartment with city view.",
                "price": 1000,
                "category": "APARTMENT",
                "property_type": "SALE",
                "address_text": "123 Street",
                "location": "POINT(0 0)",
                "bedrooms": 3,
                "bathrooms": 2,
                "area_sqft": 1500,
                "uploaded_images": [
                    {"url": "http://test.com/1.jpg", "is_featured": True},
                    {"url": "http://test.com/2.jpg", "is_featured": False},
                    {"url": "http://test.com/3.jpg", "is_featured": False},
                ],
            },
            format="json",
        )
        assert res.status_code == status.HTTP_201_CREATED
        prop_id = res.data["id"]

        # 2. List & Filter
        res = client.get(reverse("property-list"), {"min_price": 500})
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) >= 1

    def test_similar_properties_recommendation(self, verified_owner):
        user, client = verified_owner
        p1 = Property.objects.create(
            owner=user,
            title="Base",
            price=1000,
            category="RESIDENTIAL",
            location=Point(0, 0),
        )
        p2 = Property.objects.create(
            owner=user,
            title="Similar",
            price=1100,
            category="RESIDENTIAL",
            location=Point(0, 0),
        )

        res = client.get(reverse("property-similar-properties", kwargs={"pk": p1.pk}))
        assert res.status_code == status.HTTP_200_OK
        assert len(res.data) >= 1
        assert res.data[0]["title"] == "Similar"

    def test_engagement_and_notifications(self, regular_user, verified_owner):
        guest, guest_client = regular_user
        owner, owner_client = verified_owner
        prop = Property.objects.create(
            owner=owner, title="Engage Me", price=2000, location=Point(0, 0)
        )

        # 1. Review
        res = guest_client.post(
            reverse("review-list"),
            {"property": prop.pk, "rating": 5, "comment": "Nice"},
        )
        assert res.status_code == status.HTTP_201_CREATED
        assert Notification.objects.filter(user=owner, title="New Review").exists()

        # 2. Tour Request
        with patch("shared.tasks.send_email_task.delay") as mock_email:
            res = guest_client.post(
                reverse("tour-request-list"),
                {
                    "property": prop.pk,
                    "slot": "2025-12-30T10:00:00Z",
                    "message": "Let's see it",
                },
            )
            assert res.status_code == status.HTTP_201_CREATED
            assert mock_email.called
            assert Notification.objects.filter(
                user=owner, title="New Tour Request"
            ).exists()

    def test_favorite_toggle(self, regular_user, verified_owner):
        guest, guest_client = regular_user
        owner, owner_client = verified_owner
        prop = Property.objects.create(
            owner=owner, title="Fav Me", price=2000, location=Point(0, 0)
        )

        url = reverse("property-toggle-favorite", kwargs={"pk": prop.pk})
        res = guest_client.post(url)
        assert res.status_code == status.HTTP_201_CREATED
        assert Favorite.objects.filter(user=guest, property=prop).exists()

        res = guest_client.post(url)
        assert res.status_code == status.HTTP_200_OK
        assert not Favorite.objects.filter(user=guest, property=prop).exists()

    def test_permission_restrictions(self, regular_user, verified_owner):
        guest, guest_client = regular_user
        owner, owner_client = verified_owner

        # 1. Regular user cannot list tour requests
        res = guest_client.get(reverse("tour-request-list"))
        assert res.status_code == status.HTTP_403_FORBIDDEN

        # 2. Regular user CAN list favorites (updated per requirements)
        res = guest_client.get(reverse("favorite-list"))
        assert res.status_code == status.HTTP_200_OK

        # 3. Owner CAN list tour requests
        res = owner_client.get(reverse("tour-request-list"))
        assert res.status_code == status.HTTP_200_OK

        # 4. Owner CAN list favorites
        res = owner_client.get(reverse("favorite-list"))
        assert res.status_code == status.HTTP_200_OK
