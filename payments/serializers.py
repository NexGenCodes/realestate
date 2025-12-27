from rest_framework import serializers
from .models import (
    PaymentProfile,
    Transaction,
    TransactionAuditLog,
    WithdrawalRequest,
    Cancellation,
)


class PaymentProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentProfile
        fields = [
            "id",
            "user",
            "is_active",
            "cached_balance",
        ]
        read_only_fields = ["user", "cached_balance"]


class TransactionSerializer(serializers.ModelSerializer):
    property_title = serializers.CharField(source="property.title", read_only=True)
    property_id = serializers.IntegerField(source="property.id", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "property_id",
            "property_title",
            "amount",
            "flw_ref",
            "status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["flw_ref", "status", "amount", "created_at", "updated_at"]


class CancellationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cancellation
        fields = ["reason", "refund_ref", "created_at"]
        read_only_fields = ["refund_ref", "created_at"]


class WithdrawalRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = WithdrawalRequest
        fields = [
            "id",
            "amount",
            "destination_bank_code",
            "destination_account_number",
            "reference",
            "status",
            "admin_note",
            "created_at",
        ]
        read_only_fields = ["reference", "status", "admin_note", "created_at"]
