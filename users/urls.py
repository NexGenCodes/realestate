from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    ProfileView,
    OwnerRequestView,
    AdminUserViewSet,
    AdminOwnerRequestViewSet,
    SavedSearchViewSet,
    SavedSearchViewSet,
    NotificationViewSet,
)
from .admin_dashboard_views import AdminDashboardViewSet
from fcm_django.api.rest_framework import FCMDeviceAuthorizedViewSet
from .auth import (
    SignupView,
    VerifySignupView,
    ResendOtpView,
    ForgotPasswordView,
    ResetPasswordView,
    CustomTokenObtainPairView,
)
from .social_views import GoogleLogin, AppleLogin

router = DefaultRouter()
router.register(r"admin/users", AdminUserViewSet, basename="admin-users")
router.register(
    r"admin/owner-requests", AdminOwnerRequestViewSet, basename="admin-owner-requests"
)
router.register(r"admin/dashboard", AdminDashboardViewSet, basename="admin-dashboard")
router.register(r"saved-searches", SavedSearchViewSet, basename="saved-search")
router.register(r"device-tokens", FCMDeviceAuthorizedViewSet, basename="device-token")
router.register(r"notifications", NotificationViewSet, basename="notification")


urlpatterns = [
    path("auth/register/", SignupView.as_view(), name="signup"),
    path("auth/verify-signup/", VerifySignupView.as_view(), name="verify-signup"),
    path("auth/resend-otp/", ResendOtpView.as_view(), name="resend-otp"),
    path("auth/login/", CustomTokenObtainPairView.as_view(), name="token_obtain_pair"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="token_refresh"),
    path("auth/forgot-password/", ForgotPasswordView.as_view(), name="forgot-password"),
    path("auth/reset-password/", ResetPasswordView.as_view(), name="reset-password"),
    path("auth/google/", GoogleLogin.as_view(), name="google_login"),
    path("auth/apple/", AppleLogin.as_view(), name="apple_login"),
    path("profile/", ProfileView.as_view(), name="profile"),
    path("owner-requests/", OwnerRequestView.as_view(), name="owner-requests"),
    path("", include(router.urls)),
]
