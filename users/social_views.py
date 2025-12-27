from allauth.socialaccount.providers.google.views import GoogleOAuth2Adapter
from allauth.socialaccount.providers.apple.views import AppleOAuth2Adapter
from allauth.socialaccount.providers.oauth2.client import OAuth2Client
from dj_rest_auth.registration.views import SocialLoginView
from rest_framework.response import Response


class GoogleLogin(SocialLoginView):
    adapter_class = GoogleOAuth2Adapter
    # Callback URL should match what's configured in Google Console
    callback_url = "http://localhost:8000/api/v1/auth/google/callback/"
    client_class = OAuth2Client


from rest_framework.views import APIView
from rest_framework import status


class AppleLogin(APIView):
    def post(self, request):
        return Response(
            {"error": "Apple login not implemented yet"},
            status=status.HTTP_400_BAD_REQUEST,
        )


# class AppleLogin(SocialLoginView):
#     adapter_class = AppleOAuth2Adapter
#     callback_url = "http://localhost:8000/api/v1/auth/apple/callback/"
#     client_class = OAuth2Client
