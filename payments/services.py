import logging
import requests
import uuid
import json
from django.conf import settings
from django.db import transaction as db_transaction
from django.utils import timezone
from django.db import models
from .models import (
    PaymentProfile,
    Transaction,
    TransactionAuditLog,
    WithdrawalRequest,
    Cancellation,
    Property,
    LedgerEntry,
)
from shared import cache_utils, messaging

logger = logging.getLogger(__name__)


class FlutterwaveService:
    BASE_URL = "https://api.flutterwave.com/v3"
    HEADERS = {
        "Authorization": f"Bearer {settings.FLW_SECRET_KEY}",
        "Content-Type": "application/json",
    }

    @staticmethod
    def _get_payment_options(amount):
        """Helper to determine payment options based on amount."""
        if amount > 1000000:
            return "banktransfer"
        return "card,banktransfer,ussd,account"

    @staticmethod
    def generate_payment_config(transaction_obj):
        """
        Generate configuration for Frontend Widget / Mobile SDK.
        Does NOT call FLW API. Returns payload for frontend to use.
        """
        payment_options = FlutterwaveService._get_payment_options(
            transaction_obj.amount
        )

        return {
            "public_key": settings.FLW_PUBLIC_KEY,
            "tx_ref": transaction_obj.flw_ref,
            "amount": float(transaction_obj.amount),
            "currency": "NGN",
            "payment_options": payment_options,
            "customer": {
                "email": transaction_obj.payer.email,
                "phonenumber": getattr(transaction_obj.payer, "phone_number", ""),
                "name": f"{transaction_obj.payer.first_name} {transaction_obj.payer.last_name}",
            },
            "meta": {
                "property_id": transaction_obj.property.id,
                "transaction_id": transaction_obj.id,
                "consumer_id": transaction_obj.payer.id,
            },
            "customizations": {
                "title": f"Payment for {transaction_obj.property.title}",
                "description": "Property Purchase",
                "logo": "http://www.piedpiper.com/app/themes/joystick-v27/images/logo.png",
            },
        }

    @staticmethod
    def initiate_payment(transaction_obj):
        """Initialize payment with Flutterwave (Direct API integration)."""
        payment_options = FlutterwaveService._get_payment_options(
            transaction_obj.amount
        )

        payload = {
            "tx_ref": transaction_obj.flw_ref,
            "amount": str(transaction_obj.amount),
            "currency": "NGN",
            "redirect_url": f"{settings.SITE_URL}/api/payments/callback/",
            "payment_options": payment_options,
            "customer": {
                "email": transaction_obj.payer.email,
                "name": f"{transaction_obj.payer.first_name} {transaction_obj.payer.last_name}",
            },
            "meta": {
                "property_id": transaction_obj.property.id,
                "transaction_id": transaction_obj.id,
            },
            "customizations": {
                "title": f"Payment for {transaction_obj.property.title}",
                "logo": "http://www.piedpiper.com/app/themes/joystick-v27/images/logo.png",
            },
        }

        # Strategy: Collect ALL funds to Platform (Escrow).
        # Funds are held for 7 days then released to Owner via Withdrawal (Transfer).

        try:
            response = requests.post(
                f"{FlutterwaveService.BASE_URL}/payments",
                headers=FlutterwaveService.HEADERS,
                json=payload,
            )
            return response.json()
        except Exception as e:
            logger.error(f"Payment Init Error: {e}")
            raise

    @staticmethod
    def verify_transaction(tx_ref):
        try:
            response = requests.get(
                f"{FlutterwaveService.BASE_URL}/transactions/verify_by_reference?tx_ref={tx_ref}",
                headers=FlutterwaveService.HEADERS,
            )
            return response.json()
        except Exception as e:
            logger.error(f"Verification Error: {e}")
            raise

    @staticmethod
    def resolve_account(account_number, bank_code):
        payload = {"account_number": account_number, "account_bank": bank_code}
        try:
            response = requests.post(
                f"{FlutterwaveService.BASE_URL}/accounts/resolve",
                headers=FlutterwaveService.HEADERS,
                json=payload,
            )
            return response.json()
        except Exception as e:
            raise Exception(f"Account Resolution Failed: {e}")

    @staticmethod
    def initiate_transfer(amount, bank_code, account_number, narration, reference):
        """Transfer funds from Platform to User (Withdrawal/Settlement)."""
        payload = {
            "account_bank": bank_code,
            "account_number": account_number,
            "amount": float(amount),
            "narration": narration,
            "currency": "NGN",
            "reference": reference,
            "debit_currency": "NGN",
        }
        try:
            response = requests.post(
                f"{FlutterwaveService.BASE_URL}/transfers",
                headers=FlutterwaveService.HEADERS,
                json=payload,
            )
            return response.json()
        except Exception as e:
            logger.error(f"Transfer Error: {e}")
            raise

    @staticmethod
    def refund_transaction(transaction_id, amount):
        payload = {
            "amount": str(amount),
        }
        try:
            response = requests.post(
                f"{FlutterwaveService.BASE_URL}/transactions/{transaction_id}/refund",
                headers=FlutterwaveService.HEADERS,
                json=payload,
            )
            return response.json()
        except Exception as e:
            logger.error(f"Refund Error: {e}")
            raise


class PaymentService:
    @staticmethod
    def process_webhook_payment_success(payload):
        """
        Handle successful payment webhook.
        SAFEGUARD: Idempotency & Concurrency Locking.
        """
        tx_ref = payload.get("txRef")
        flw_id = payload.get("id")

        with db_transaction.atomic():
            # Lock the transaction row
            try:
                tx = Transaction.objects.select_for_update().get(flw_ref=tx_ref)
            except Transaction.DoesNotExist:
                logger.error(f"Transaction with ref {tx_ref} not found.")
                return

            # Idempotency Check
            if tx.status not in [Transaction.Status.PENDING]:
                logger.info(
                    f"Transaction {tx_ref} already processed (Status: {tx.status}). Ignoring."
                )
                return

            # Verify Amount (Security)
            charged_amount = payload.get("amount")
            if float(charged_amount) < float(tx.amount):
                logger.warning(
                    f"Underpayment for {tx_ref}. Expected {tx.amount}, got {charged_amount}"
                )
                # Handle underpayment logic? For now, leave PENDING or FAILED.
                return

            # --- SECONDARY VERIFICATION (Double Check) ---
            try:
                verify_res = FlutterwaveService.verify_transaction(tx_ref)
                if verify_res.get("status") != "success":
                    logger.error(
                        f"Secondary Verification Failed: API returned error for {tx_ref}"
                    )
                    return

                # Check IDs and amounts from the actual API response
                api_data = verify_res.get("data", {})
                if str(api_data.get("id")) != str(flw_id):
                    logger.error(
                        f"Secondary Verification Failed: ID mismatch for {tx_ref}"
                    )
                    return

                if float(api_data.get("amount", 0)) < float(tx.amount):
                    logger.error(
                        f"Secondary Verification Failed: Amount mismatch for {tx_ref}"
                    )
                    return
            except Exception as e:
                logger.error(f"Secondary Verification Exception: {e}")
                return

            # Update Status
            old_status = tx.status
            tx.status = Transaction.Status.CLEARING  # Escrow starts
            tx.save()

            # Trigger Notification
            messaging.notify_payment_success(tx)

            # Invalidate Wallet Caches
            PaymentService.invalidate_wallet_cache(tx.payer)
            PaymentService.invalidate_wallet_cache(tx.owner)

            # Create Audit Log
            TransactionAuditLog.objects.create(
                transaction=tx,
                old_status=old_status,
                new_status=tx.status,
                changed_by=None,  # System
                ip_address="127.0.0.1",
            )

            # Logic: We hold funds. We do NOT credit PaymentProfile yet.
            # Balance on PaymentProfile is "Available to Withdraw".
            # Funds in CLEARING are NOT available.

    @staticmethod
    def invalidate_wallet_cache(user):
        """Clear Redis cache for user's wallet."""
        cache_key = f"wallet_balance_{user.id}"
        cache_utils.delete_key(cache_key)

    @staticmethod
    def get_wallet_balance(user):
        """
        Calculate user's wallet balance from Transaction Ledger.
        Uses Redis Caching for performance.
        """
        cache_key = f"wallet_balance_{user.id}"
        cached_data = cache_utils.get_key(cache_key)
        if cached_data:
            return cached_data

        # 1. Total Earnings (Released)
        total_released = (
            user.sales.filter(status=Transaction.Status.RELEASED).aggregate(
                models.Sum("owner_amount")
            )["owner_amount__sum"]
            or 0
        )

        # 2. Clearing (Pending)
        total_clearing = (
            user.sales.filter(status=Transaction.Status.CLEARING).aggregate(
                models.Sum("owner_amount")
            )["owner_amount__sum"]
            or 0
        )

        # 3. Total Withdrawn (Processed + Pending Requests)
        # Pending requests are deducted from available to prevent double spend
        total_withdrawn = (
            user.withdrawals.filter(
                status__in=[
                    WithdrawalRequest.Status.PROCESSED,
                    WithdrawalRequest.Status.PENDING,
                ]
            ).aggregate(models.Sum("amount"))["amount__sum"]
            or 0
        )

        available = total_released - total_withdrawn
        ledger_balance = available + total_clearing  # What they "own" in total

        # --- Recent Activity (Ledger) ---
        recent_activity = LedgerEntry.objects.filter(user=user).order_by("-created_at")[
            :10
        ]
        activity_data = [
            {
                "id": entry.id,
                "amount": float(entry.amount),
                "type": entry.entry_type,
                "description": entry.description,
                "date": entry.created_at.isoformat(),
            }
            for entry in recent_activity
        ]

        result = {
            "available_balance": float(available),
            "ledger_balance": float(ledger_balance),
            "clearing_balance": float(total_clearing),
            "total_withdrawn": float(total_withdrawn),
            "recent_activity": activity_data,
        }

        # Cache the result
        cache_utils.set_key(cache_key, result, ttl=settings.CACHE_TTL)
        return result

    @staticmethod
    def process_withdrawal(user, amount, bank_details):
        """
        Process a withdrawal request.
        SAFEGUARD: Concurrency Locking on PaymentProfile.
        """
        with db_transaction.atomic():
            profile = PaymentProfile.objects.select_for_update().get(user=user)

            # Verify Balance (This 'cached_balance' should be maintained strictly)
            # OR we calculate dynamic balance: Sum(Released Sales) - Sum(Withdrawals)
            # Dynamic is safer for consistency.

            total_sales = (
                user.sales.filter(status=Transaction.Status.RELEASED).aggregate(
                    models.Sum("owner_amount")
                )["owner_amount__sum"]
                or 0
            )
            total_withdrawn = (
                user.withdrawals.filter(
                    status__in=[
                        WithdrawalRequest.Status.PROCESSED,
                        WithdrawalRequest.Status.PENDING,
                    ]
                ).aggregate(models.Sum("amount"))["amount__sum"]
                or 0
            )

            available_balance = total_sales - total_withdrawn

            # Determine Withdrawal Fee
            withdrawal_fee = 0
            if user.role == "USER":
                # Users pay 2% on withdrawal (or implied logic)
                withdrawal_fee = amount * 0.02

            # Owners already paid 10% on the *Incoming* transaction (Transaction.system_fee).
            # So on withdrawal, we might likely just charge transfer fee or nothing.
            # User said "10% minus for owners", which matches our Transaction logic (90% owner_amount).

            total_debit = amount + withdrawal_fee

            if available_balance < total_debit:
                raise Exception(_("Insufficient funds including fees."))

            if amount < 5000:
                raise Exception(_("Minimum withdrawal is ₦5,000."))

            # Verify Bank (Redundant check but good)
            resolved = FlutterwaveService.resolve_account(
                bank_details["account_number"], bank_details["bank_code"]
            )
            if resolved["status"] != "success":
                raise Exception(_("Invalid bank account."))

            # Create Withdrawal Request
            ref = f"W-{uuid.uuid4().hex[:12].upper()}"
            withdrawal = WithdrawalRequest.objects.create(
                user=user,
                amount=amount,
                # We should probably store fee in model, but for now we just track it in 'admin_note' or similar
                # Or we assume amount is gross?
                # Let's say we debit 'amount + fee' from ledger, but send 'amount' to bank.
                # Ideally WithdrawalRequest should have a 'fee' field.
                destination_bank_code=bank_details["bank_code"],
                destination_account_number=bank_details["account_number"],
                reference=ref,
                status=WithdrawalRequest.Status.PENDING,
                admin_note=f"Fee: {withdrawal_fee}",
            )

            # Initiate Transfer
            try:
                transfer_res = FlutterwaveService.initiate_transfer(
                    amount,  # We send the requested amount
                    bank_details["bank_code"],
                    bank_details["account_number"],
                    "Fund Withdrawal",
                    ref,
                )

                if transfer_res["status"] == "success":
                    withdrawal.status = WithdrawalRequest.Status.PROCESSED
                    withdrawal.save()

                    # Auto-Save Bank Details to Profile
                    profile = user.payment_profile
                    profile.bank_code = bank_details["bank_code"]
                    profile.account_number = bank_details["account_number"]

                    # Ideally we should save the account name too.
                    # resolved data is available in 'resolved' variable above
                    if resolved["status"] == "success":
                        profile.account_name = resolved["data"]["account_name"]
                        # We don't strictly have bank_name here unless we fetch it,
                        # but we can save what we have.

                    profile.save()

                    # Create Ledger Entry (DEBIT)
                    LedgerEntry.objects.create(
                        user=user,
                        amount=total_debit,  # Original Amount + Fee
                        entry_type=LedgerEntry.EntryType.DEBIT,
                        description=f"Withdrawal Processing: {bank_details['bank_code']} | {bank_details['account_number']}",
                        withdrawal=withdrawal,
                    )

                    # Notify Success
                    messaging.notify_withdrawal_status(withdrawal)
                else:
                    withdrawal.status = WithdrawalRequest.Status.FAILED
                    withdrawal.admin_note = transfer_res.get(
                        "message", "Transfer Failed"
                    )
                    withdrawal.save()

                    # Notify Failure
                    messaging.notify_withdrawal_status(withdrawal)

                    raise Exception(f"Transfer failed: {transfer_res.get('message')}")

                # Invalidate Cache
                PaymentService.invalidate_wallet_cache(user)

            except Exception as e:
                withdrawal.status = WithdrawalRequest.Status.FAILED
                withdrawal.save()
                raise e

    @staticmethod
    def cancel_transaction(transaction, reason, account_details):
        """
        Handle cancellation within 7 days.
        """
        with db_transaction.atomic():
            tx = Transaction.objects.select_for_update().get(id=transaction.id)

            if tx.status != Transaction.Status.CLEARING:
                raise Exception("Cannot cancel transaction that is not in clearing.")

            days_diff = (timezone.now() - tx.created_at).days
            if days_diff >= 7:
                raise Exception("7-day cancellation window has passed.")

            # Calculate 98% refund
            refund_amount = tx.amount * 0.98

            # Call FLW Refund
            try:
                # We need the FLW Transaction ID. We try to verify via ref first.
                verify_res = FlutterwaveService.verify_transaction(tx.flw_ref)
                if verify_res["status"] == "success":
                    flw_id = verify_res["data"]["id"]
                    FlutterwaveService.refund_transaction(flw_id, refund_amount)
                else:
                    logger.error(
                        f"Could not verify transaction {tx.flw_ref} for refund."
                    )
                    # We proceed to cancel locally but flag for Admin?
                    # For safety, we should probably fail.
                    raise Exception(
                        "Could not verify transaction with Payment Gateway."
                    )
            except Exception as e:
                logger.error(f"Refund Exception: {e}")
                # For compliance, if refund fails, we probably shouldn't cancel logic entirely?
                # Or we mark status as 'REFUND_FAILED'
                # Let's start with strict failure to avoid inconsistencies.
                raise Exception("Refund initiation failed. Please contact support.")

            # Update Status
            old_status = tx.status
            tx.status = Transaction.Status.CANCELLED
            tx.save()

            # Create Cancellation Record
            Cancellation.objects.create(
                transaction=tx, reason=reason, account_details=account_details
            )

            # Audit Log
            TransactionAuditLog.objects.create(
                transaction=tx,
                old_status=old_status,
                new_status=tx.status,
                ip_address="127.0.0.1",
            )

            # Ban Logic Check
            # Check number of cancels + reports for this property
            property_obj = tx.property
            bad_count = Cancellation.objects.filter(
                transaction__property=property_obj
            ).count()
            bad_count += (
                property_obj.reports.count()
            )  # assuming related_name='reports' exists

            if bad_count >= 5:
                property_obj.is_banned = True
                property_obj.ban_reason = (
                    "System Ban: Exceeded 5 complaints/cancellations."
                )
                property_obj.save()
                # Notify Owner/Admin (Logic elsewhere)

    @staticmethod
    def process_admin_withdrawal(amount, bank_details):
        """
        Process admin withdrawal (debiting main platform account).
        """
        ref = f"ADMIN-W-{uuid.uuid4().hex[:12].upper()}"

        # Verify Amount? Admin can presumably check their own dashboard.
        # But we effectively just call transfer.

        try:
            res = FlutterwaveService.initiate_transfer(
                amount,
                bank_details["bank_code"],
                bank_details["account_number"],
                "Admin Withdrawal",
                ref,
            )
            return res
        except Exception as e:
            logger.error(f"Admin Withdrawal Failed: {e}")
            raise e
