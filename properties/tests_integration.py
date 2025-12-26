import pytest
from django.urls import reverse
from rest_framework import status
from django.contrib.gis.geos import Point
from users.models import User
from properties.models import Property, Favorite


@pytest.mark.django_db
class TestPropertyEndpoints:
    @pytest.fixture(autouse=True)
    def setup_data(self, client):
        self.client = client
        # Create users
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="password123"
        )
        self.owner = User.objects.create_user(
            username="owner",
            email="owner@example.com",
            password="password123",
            role=User.Role.OWNER,
        )
        self.user = User.objects.create_user(
            username="user",
            email="user@example.com",
            password="password123",
            role=User.Role.USER,
        )

        # Get tokens (simulated for testing)
        self.client.force_authenticate(user=self.owner)

    def test_create_property_validation(self):
        """Test creating property with valid and invalid image counts."""
        url = reverse("property-list")
        data = {
            "title": "Nice House",
            "description": "A very nice house",
            "category": "HOUSE",
            "location": "POINT(10 10)",
            "address_text": "123 Street",
            "price": "1000.00",
            "uploaded_images": [
                {"url": "http://img1.com", "is_featured": True}
            ],  # Too few
        }

        # 1. Test fail with 1 image
        response = self.client.post(url, data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "images" in str(response.data)

        # 2. Test success with 3 images
        data["uploaded_images"] = [
            {"url": "http://img1.com", "is_featured": True},
            {"url": "http://img2.com"},
            {"url": "http://img3.com"},
        ]
        response = self.client.post(url, data, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert Property.objects.count() == 1

    def test_property_visibility(self):
        """Test that regular users can only see available properties."""
        Property.objects.create(
            owner=self.owner,
            title="Available",
            category="HOUSE",
            price=100,
            location=Point(10, 10),
            status=Property.Status.AVAILABLE,
        )
        Property.objects.create(
            owner=self.owner,
            title="Sold",
            category="HOUSE",
            price=100,
            location=Point(10, 10),
            status=Property.Status.SOLD,
        )

        self.client.force_authenticate(user=self.user)
        url = reverse("property-list")
        response = self.client.get(url)
        assert len(response.data["results"]) == 1
        assert response.data["results"][0]["title"] == "Available"

    def test_favorite_automation(self):
        """Test listing is removed from favorites when sold/rented."""
        prop = Property.objects.create(
            owner=self.owner,
            title="Test Prop",
            category="HOUSE",
            price=100,
            location=Point(10, 10),
            status=Property.Status.AVAILABLE,
        )
        Favorite.objects.create(user=self.user, property=prop)

        assert Favorite.objects.count() == 1

        # Mark as sold
        self.client.force_authenticate(user=self.owner)
        url = reverse("property-mark-as-sold", args=[prop.id])
        response = self.client.post(url)
        assert response.status_code == status.HTTP_200_OK

        # Verify favorite is gone
        assert Favorite.objects.count() == 0

    def test_ban_and_appeal(self):
        """Test the ban and appeal flow."""
        prop = Property.objects.create(
            owner=self.owner,
            title="Banned Prop",
            category="HOUSE",
            price=100,
            location=Point(10, 10),
            status=Property.Status.AVAILABLE,
        )

        # Admin bans
        self.client.force_authenticate(user=self.admin)
        url = reverse("property-ban", args=[prop.id])
        self.client.post(url, {"reason": "Bad content"})

        prop.refresh_from_db()
        assert prop.is_banned is True
        assert prop.status == Property.Status.BANNED

        # Owner appeals
        self.client.force_authenticate(user=self.owner)
        url = reverse("property-appeal", args=[prop.id])
        response = self.client.post(url, {"appeal_text": "Please unban me"})
        assert response.status_code == status.HTTP_200_OK

        prop.refresh_from_db()
        assert prop.appeal_status == "PENDING"
