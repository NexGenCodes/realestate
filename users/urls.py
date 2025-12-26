from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from .views import (
    ProfileView,
    OwnerRequestView,
    AdminUserViewSet,
    AdminOwnerRequestViewSet,
)
from .auth import (
    SignupView,
    VerifySignupView,
    ResendOtpView,
    ForgotPasswordView,
    ResetPasswordView,
)

router = DefaultRouter()
router.register(r"admin/users", AdminUserViewSet, basename="admin-users")
router.register(
    r"admin/owner-requests", AdminOwnerRequestViewSet, basename="admin-owner-requests"
)

urlpatterns = [
    path("auth/register/", SignupView.as_view(), name="signup"),
    path("auth/verify-signup/", VerifySignupView.as_view(), name="verify-signup"),
    path("auth/resend-otp/", ResendOtpView.as_view(), name="resend-otp"),
    path("auth/login/", TokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("owner-requests/", OwnerRequestView.as_view(), name="owner-requests"),
    path("", include(router.urls)),
]
