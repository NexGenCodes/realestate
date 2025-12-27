import pytest
import uuid
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from .models import Transaction, WithdrawalRequest, LedgerEntry, PaymentProfile
from properties.models import Property

User = get_user_model()


@pytest.fixture
def test_password():
    return "TemporaryPassword123!"


@pytest.fixture
def owner_user(db, test_password):
    user = User.objects.create_user(
        email="owner@paytest.com",
        password=test_password,
        role=User.Role.OWNER,
        is_verified_owner=True,
    )
    # Ensure PaymentProfile exists (usually created via signal or similar, but let's be explicit if needed)
    PaymentProfile.objects.get_or_create(user=user)
    return user


@pytest.fixture
def buyer_user(db, test_password):
    user = User.objects.create_user(email="buyer@paytest.com", password=test_password)
    return user


@pytest.fixture
def property_obj(owner_user):
    return Property.objects.create(
        owner=owner_user,
        title="Payment Test Villa",
        price=100000,  # 100k
        status=Property.Status.AVAILABLE,
        latitude=6.5,
        longitude=3.4,
    )


@pytest.mark.django_db
class TestPaymentSystem:

    def test_initiate_payment(self, buyer_user, property_obj):
        client = APIClient()
        client.force_authenticate(user=buyer_user)

        res = client.post(reverse("payment-initiate"), {"property_id": property_obj.id})
        assert res.status_code == status.HTTP_201_CREATED
        assert "public_key" in res.data
        assert "tx_ref" in res.data

        # Verify transaction in DB
        tx = Transaction.objects.get(flw_ref=res.data["tx_ref"])
        assert tx.status == Transaction.Status.PENDING
        assert tx.amount == property_obj.price

    @patch("payments.services.FlutterwaveService.verify_transaction")
    def test_webhook_payment_success(self, mock_verify, buyer_user, property_obj):
        # 1. Setup pending transaction
        tx = Transaction.objects.create(
            property=property_obj,
            payer=buyer_user,
            owner=property_obj.owner,
            amount=100000,
            system_fee=10000,
            owner_amount=90000,
            flw_ref="TEST-TX-123",
            status=Transaction.Status.PENDING,
        )

        # 2. Mock FLW Verification API
        mock_verify.return_value = {
            "status": "success",
            "data": {"id": 12345, "amount": 100000, "status": "successful"},
        }

        # 3. Simulate Webhook
        client = APIClient()
        from django.conf import settings

        headers = {"HTTP_VERIF_HASH": settings.FLW_SECRET_HASH}
        payload = {
            "event": "charge.completed",
            "data": {
                "id": 12345,
                "txRef": "TEST-TX-123",
                "amount": 100000,
                "status": "successful",
            },
        }
        res = client.post(reverse("payment-webhook"), payload, format="json", **headers)
        assert res.status_code == status.HTTP_200_OK

        # 4. Verify Status Change (Escrow starts)
        tx.refresh_from_db()
        assert tx.status == Transaction.Status.CLEARING

    def test_escrow_release_task(self, owner_user, property_obj, buyer_user):
        # Create a transaction that has been in CLEARING for 8 days
        tx = Transaction.objects.create(
            property=property_obj,
            payer=buyer_user,
            owner=owner_user,
            amount=100000,
            system_fee=10000,
            owner_amount=90000,
            flw_ref="OLD-TX",
            status=Transaction.Status.CLEARING,
        )
        tx.created_at = timezone.now() - timedelta(days=8)
        tx.save()

        # Run the release task
        from payments.tasks import release_payments

        release_payments()

        tx.refresh_from_db()
        assert tx.status == Transaction.Status.RELEASED

        # Verify Ledger Entry (CREDIT)
        assert LedgerEntry.objects.filter(
            user=owner_user, amount=90000, entry_type=LedgerEntry.EntryType.CREDIT
        ).exists()

    @patch("payments.services.FlutterwaveService.resolve_account")
    @patch("payments.services.FlutterwaveService.initiate_transfer")
    def test_withdrawal_workflow(
        self, mock_transfer, mock_resolve, owner_user, property_obj, buyer_user
    ):
        # 1. Give owner some released funds
        tx = Transaction.objects.create(
            property=property_obj,
            payer=buyer_user,
            owner=owner_user,
            amount=100000,
            system_fee=10000,
            owner_amount=90000,
            flw_ref="REL-TX",
            status=Transaction.Status.RELEASED,
        )
        # Explicitly create a LedgerEntry for the released funds to ensure balance calculation is accurate
        LedgerEntry.objects.create(
            user=owner_user,
            transaction=tx,
            amount=tx.owner_amount,
            entry_type=LedgerEntry.EntryType.CREDIT,
            description=f"Funds released from transaction {tx.flw_ref}",
        )

        # 2. Mock Bank Resolution & Transfer
        mock_resolve.return_value = {
            "status": "success",
            "data": {"account_name": "Test Owner"},
        }
        mock_transfer.return_value = {
            "status": "success",
            "data": {"reference": "W-REF"},
        }

        # 3. Request Withdrawal
        client = APIClient()
        client.force_authenticate(user=owner_user)

        withdrawal_data = {
            "amount": 50000,
            "bank_details": {"account_number": "0123456789", "bank_code": "044"},
        }
        res = client.post(reverse("owner-withdrawal"), withdrawal_data, format="json")
        if res.status_code != 200:
            print(res.data)
        assert res.status_code == status.HTTP_200_OK

        # 4. Verify Ledger Entry (DEBIT)
        assert LedgerEntry.objects.filter(
            user=owner_user, amount__gte=50000, entry_type=LedgerEntry.EntryType.DEBIT
        ).exists()

        # 5. Check Wallet Balance
        res = client.get(reverse("wallet"))
        assert res.data["available_balance"] == 40000  # 90k - 50k
