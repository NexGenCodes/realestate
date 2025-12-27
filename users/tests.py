import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.core.cache import cache
from unittest.mock import patch
from .models import OwnerRequest, Notification

User = get_user_model()


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def test_password():
    return "TemporaryPassword123!"


@pytest.fixture
def authenticated_user(db, test_password):
    user = User.objects.create_user(
        email="testuser@example.com",
        password=test_password,
        first_name="Test",
        last_name="User",
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


@pytest.fixture
def admin_user(db, test_password):
    admin = User.objects.create_superuser(
        email="admin@test.com", password=test_password
    )
    client = APIClient()
    client.force_authenticate(user=admin)
    return admin, client


@pytest.mark.django_db
class TestUsersApp:

    @patch("users.auth.send_otp_email")
    def test_auth_registration_flow(self, mock_email, api_client, test_password):
        # 1. Signup
        signup_data = {
            "email": "newuser@example.com",
            "password": test_password,
            "first_name": "New",
            "last_name": "User",
        }
        res = api_client.post(reverse("signup"), signup_data)
        assert res.status_code == status.HTTP_201_CREATED

        # 2. Verify Signup (using cached OTP)
        otp_key = "signup_newuser@example.com"
        cached = cache.get(otp_key)
        assert cached is not None

        verify_data = {"email": "newuser@example.com", "otp_code": cached["otp"]}
        res = api_client.post(reverse("verify-signup"), verify_data)
        assert res.status_code == status.HTTP_201_CREATED

        # 3. Login
        login_data = {"email": "newuser@example.com", "password": test_password}
        res = api_client.post(reverse("token_obtain_pair"), login_data)
        assert res.status_code == status.HTTP_200_OK
        assert "access" in res.data

    def test_profile_access(self, authenticated_user):
        user, client = authenticated_user
        res = client.get(reverse("profile"))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["email"] == user.email

    def test_owner_request_to_approval_flow(self, authenticated_user, admin_user):
        user, client = authenticated_user
        admin, admin_client = admin_user

        # 1. Submit Request
        with patch("cloudinary.uploader.upload") as mock_upload:
            mock_upload.return_value = {"secure_url": "http://test.com/doc.pdf"}
            from django.core.files.uploadedfile import SimpleUploadedFile

            doc = SimpleUploadedFile(
                "id.pdf", b"content", content_type="application/pdf"
            )

            res = client.post(
                reverse("owner-requests"),
                {"id_type": "NATIONAL_ID", "reason": "Test reason", "documents": doc},
                format="multipart",
            )
            assert res.status_code == status.HTTP_201_CREATED
            request_id = res.data["id"]

        # 2. Admin Approval
        with patch("shared.tasks.send_email_task.delay") as mock_email_task:
            res = admin_client.patch(
                reverse("admin-owner-requests-detail", kwargs={"pk": request_id}),
                {"status": "APPROVED", "admin_notes": "Passed"},
            )
            assert res.status_code == status.HTTP_200_OK
            assert mock_email_task.called

            user.refresh_from_db()
            assert user.role == User.Role.OWNER
            assert user.is_verified_owner is True
            assert Notification.objects.filter(
                user=user, title="Owner Request Approved"
            ).exists()

    def test_health_check(self, api_client):
        res = api_client.get(reverse("health-check"))
        assert res.status_code == status.HTTP_200_OK
        assert res.data["status"] == "healthy"
