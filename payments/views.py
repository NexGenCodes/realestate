from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, generics
from django.conf import settings
from .models import Transaction, WithdrawalRequest
from .services import PaymentService, FlutterwaveService
from rest_framework.decorators import permission_classes
from .serializers import TransactionSerializer


import logging
import uuid

logger = logging.getLogger(__name__)


class WebhookView(APIView):
    permission_classes = [
        permissions.AllowAny
    ]  # Webhook is public but signature verified

    def post(self, request):
        secret_hash = settings.FLW_SECRET_HASH
        signature = request.headers.get("verif-hash")

        if not signature or signature != secret_hash:
            logger.warning("Webhook Signature Verification Failed")
            return Response(status=status.HTTP_403_FORBIDDEN)

        payload = request.data
        event_type = payload.get("event")
        data = payload.get("data")

        if event_type == "charge.completed" and data.get("status") == "successful":
            PaymentService.process_webhook_payment_success(data)

        return Response(status=status.HTTP_200_OK)


class TransactionListView(generics.ListAPIView):
    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == "OWNER":
            return Transaction.objects.filter(owner=user).select_related("property")
        return Transaction.objects.filter(payer=user).select_related("property")


class CancelTransactionView(APIView):
    def post(self, request, pk):
        try:
            transaction = Transaction.objects.get(pk=pk, payer=request.user)
            reason = request.data.get("reason")
            account_details = request.data.get(
                "account_details"
            )  # {account_number, bank_code}

            if not reason or not account_details:
                return Response(
                    {"error": "Reason and account details required"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            PaymentService.cancel_transaction(transaction, reason, account_details)
            return Response({"message": "Transaction cancelled and refund initiated."})
        except Transaction.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Cancel Error: {e}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class OwnerWithdrawalView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        if request.user.role != "OWNER":
            return Response(
                {"error": "Only owners can withdraw."}, status=status.HTTP_403_FORBIDDEN
            )

        amount = request.data.get("amount")
        bank_details = request.data.get("bank_details")  # {account_number, bank_code}

        if not amount or not bank_details:
            return Response(
                {"error": "Amount and bank_details required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            PaymentService.process_withdrawal(request.user, float(amount), bank_details)
            return Response({"message": "Withdrawal processed successfully."})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class AdminWithdrawalView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        # Show total platform earnings (10% fees from VALID transactions)
        # VALID = RELEASED or CLEARING (technically we have the money, but safely only withdraw RELEASED fees)
        total_fees = (
            Transaction.objects.filter(
                status__in=[Transaction.Status.RELEASED, Transaction.Status.CLEARING]
            ).aggregate(models.Sum("system_fee"))["system_fee__sum"]
            or 0
        )
        return Response({"platform_earnings": total_fees})

    def post(self, request):
        amount = request.data.get("amount")
        bank_details = request.data.get("bank_details")

        if not amount or not bank_details:
            return Response(
                {"error": "Amount and bank_details required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # For Admin, we debit the main account.
        # FLW Transfer debits the merchant balance by default.
        # So we just ensure we don't withdraw more than we "own" (system_fee sum).
        # Note: This check requires accurate accounting.

        try:
            # Simple transfer call via Helper
            res = PaymentService.process_admin_withdrawal(float(amount), bank_details)
            return Response({"message": "Admin withdrawal initiated.", "data": res})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


class WalletView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user
        balance_data = PaymentService.get_wallet_balance(user)
        return Response(balance_data)


class VerifyBankAccountView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        account_number = request.data.get("account_number")
        bank_code = request.data.get("bank_code")

        if not account_number or not bank_code:
            return Response(
                {"error": "account_number and bank_code required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Call Service
            res = FlutterwaveService.resolve_account(account_number, bank_code)

            if res.get("status") == "success":
                return Response(res["data"])
            else:
                return Response(
                    {"error": res.get("message", "Could not resolve account")},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        except Exception as e:
            logger.error(f"Verification Error: {e}")
            return Response(
                {"error": "Failed to verify account details."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class InitiatePaymentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        property_id = request.data.get("property_id")
        if not property_id:
            return Response(
                {"error": "property_id is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # 1. Get Property (using the model imported implicitly or add import)
            from properties.models import Property

            property_obj = Property.objects.get(id=property_id)

            if not property_obj.is_available:
                return Response(
                    {"error": "Property is not available for purchase"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 2. Prevent Owner from buying their own property
            if property_obj.owner == request.user:
                return Response(
                    {"error": "You cannot buy your own property"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # 3. Create Transaction Record (PENDING)
            # Check for existing pending transaction for this user/property to avoid duplicates?
            # Ideally yes, but multiple attempts are common. We just create a new ref.

            tx_ref = f"TX-{uuid.uuid4().hex[:12].upper()}"
            amount = property_obj.price
            system_fee = amount * 0.10
            owner_amount = amount - system_fee

            transaction = Transaction.objects.create(
                property=property_obj,
                payer=request.user,
                owner=property_obj.owner,
                amount=amount,
                flw_ref=tx_ref,
                system_fee=system_fee,
                owner_amount=owner_amount,
                status=Transaction.Status.PENDING,
            )

            # 4. Generate Widget Config
            config = FlutterwaveService.generate_payment_config(transaction)

            return Response(config, status=status.HTTP_201_CREATED)

        except Property.DoesNotExist:
            return Response(
                {"error": "Property not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            logger.error(f"Initiation Logic Error: {e}")
            return Response(
                {"error": "Failed to initiate payment"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
