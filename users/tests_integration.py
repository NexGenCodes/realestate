import logging
from unittest.mock import patch
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from django.contrib.auth import get_user_model
from django.core.cache import cache
from users.models import OwnerRequest

User = get_user_model()
logger = logging.getLogger(__name__)


class APIIntegrationTests(APITestCase):
    def setUp(self):
        self.signup_url = reverse("signup")
        self.verify_signup_url = reverse("verify-signup")
        self.login_url = reverse("token_obtain_pair")
        self.profile_url = reverse("profile")
        self.owner_request_url = reverse("owner-requests")
        self.owner_verify_url = reverse("owner-requests-verify")

        self.signup_data = {
            "email": "testuser@example.com",
            "username": "testuser",
            "password": "TemporaryPassword123!",
            "first_name": "Test",
            "last_name": "User",
        }

    @patch("users.auth.send_otp_email")
    def test_complete_signup_and_login_flow(self, mock_send_email):
        """Test the full flow from signup to profile access."""
        # 1. Signup
        response = self.client.post(self.signup_url, self.signup_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(mock_send_email.called)

        # Get OTP from cache
        otp_key = f"signup_testuser@example.com"
        cached_data = cache.get(otp_key)
        self.assertIsNotNone(cached_data)
        otp = cached_data["otp"]

        # 2. Verify Signup
        verify_data = {"email": self.signup_data["email"], "otp_code": otp}
        response = self.client.post(self.verify_signup_url, verify_data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        # 3. Login
        login_payload = {
            "username": self.signup_data["username"],
            "password": self.signup_data["password"],
        }
        response = self.client.post(self.login_url, login_payload)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        access_token = response.data["access"]

        # 4. Access Profile
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access_token}")
        response = self.client.get(self.profile_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["username"], "testuser")

    @patch("users.views.send_phone_otp_sms")
    def test_owner_request_to_approval_flow(self, mock_send_sms):
        """Test the flow from owner request submission to admin approval."""
        # Setup: Create and verify a user
        user = User.objects.create_user(
            username="owner_candidate",
            email="candidate@example.com",
            password="Password123!",
            role=User.Role.USER,
        )
        self.client.force_authenticate(user=user)

        # 1. Submit Owner Request
        # Note: In real scenarios, a file would be uploaded. Cloudinary is mocked in settings or by virtue of not hitting real network.
        # However, for tests, we should mock the Cloudinary upload if possible or assume URL persistence works.
        # Since we use serializers that call cloudinary.uploader.upload, we should patch it.

        with patch("cloudinary.uploader.upload") as mock_upload:
            mock_upload.return_value = {
                "secure_url": "https://res.cloudinary.com/test/doc.pdf"
            }

            # Simple file mock for the request
            from django.core.files.uploadedfile import SimpleUploadedFile

            doc_file = SimpleUploadedFile(
                "docs.pdf", b"file_content", content_type="application/pdf"
            )

            request_data = {
                "phone_number": "+2348000000000",
                "documents": doc_file,
                "business_name": "Test Real Estate",
                "business_address": "123 Street",
            }
            response = self.client.post(
                self.owner_request_url, request_data, format="multipart"
            )
            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            request_id = response.data["id"]

            # 2. Verify Phone OTP
            otp_key = f"owner_otp_{request_id}"
            cached_data = cache.get(otp_key)
            otp = cached_data["otp"]

            verify_data = {"request_id": request_id, "otp_code": otp}
            response = self.client.post(self.owner_verify_url, verify_data)
            self.assertEqual(response.status_code, status.HTTP_200_OK)

            # 3. Admin Approval
            admin = User.objects.create_superuser(
                username="admin", email="admin@test.com", password="adminpassword"
            )
            self.client.force_authenticate(user=admin)

            admin_url = reverse(
                "admin-owner-requests-detail", kwargs={"pk": request_id}
            )
            approval_data = {"status": OwnerRequest.Status.APPROVED}

            with patch("users.views.send_owner_approval_email") as mock_approval_email:
                response = self.client.patch(admin_url, approval_data)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

                # Check user role promoted
                user.refresh_from_db()
                self.assertEqual(user.role, User.Role.OWNER)
                self.assertTrue(mock_approval_email.called)

    def test_health_check(self):
        """Test the system health check endpoint."""
        url = reverse("health-check")
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "healthy")
