from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions

from drf_yasg.utils import swagger_auto_schema


class HealthCheckView(APIView):
    permission_classes = [permissions.AllowAny]

    @swagger_auto_schema(
        operation_summary="System Health Check",
        operation_description="Check if the real estate backend services are operational.",
        tags=["System Health"],
    )
    def get(self, request):
        return Response(
            {"status": "healthy", "message": "Real Estate Backend is running"},
            status=status.HTTP_200_OK,
        )
