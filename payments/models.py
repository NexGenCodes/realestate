from django.db import models
from django.conf import settings
from django.utils.translation import gettext_lazy as _
from properties.models import Property


class PaymentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payment_profile",
    )
    is_active = models.BooleanField(default=True)

    # Cache verified details for withdrawals
    bank_code = models.CharField(max_length=10, blank=True)
    account_number = models.CharField(max_length=20, blank=True)
    bank_name = models.CharField(max_length=100, blank=True)
    account_name = models.CharField(max_length=255, blank=True)

    # We cache balance to reduce API calls, but ALWAYS verify with API before withdrawal
    cached_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Payment Profile for {self.user.email}"


class Transaction(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        CLEARING = "CLEARING", _("Clearing (Escrow)")
        RELEASED = "RELEASED", _("Released")
        CANCELLED = "CANCELLED", _("Cancelled")
        WITHDRAWN = "WITHDRAWN", _("Withdrawn")
        FAILED = "FAILED", _("Failed")

    property = models.ForeignKey(
        Property, on_delete=models.SET_NULL, null=True, related_name="transactions"
    )
    payer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="purchases"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="sales"
    )

    amount = models.DecimalField(max_digits=12, decimal_places=2)
    flw_ref = models.CharField(max_length=100, unique=True)

    # Fee Breakdown
    system_fee = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="10% Platform Fee"
    )
    owner_amount = models.DecimalField(
        max_digits=12, decimal_places=2, help_text="90% Owner Share"
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True
    )

    # For dispute window logic
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.flw_ref} - {self.amount} ({self.status})"


class TransactionAuditLog(models.Model):
    transaction = models.ForeignKey(
        Transaction, on_delete=models.CASCADE, related_name="audit_logs"
    )
    old_status = models.CharField(max_length=20)
    new_status = models.CharField(max_length=20)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log: {self.transaction.flw_ref} {self.old_status}->{self.new_status}"


class Cancellation(models.Model):
    transaction = models.OneToOneField(
        Transaction, on_delete=models.CASCADE, related_name="cancellation"
    )
    reason = models.TextField()
    refund_ref = models.CharField(max_length=100, blank=True, null=True)

    # Store user provided details for the manual refund trigger (though automated via API)
    account_details = models.JSONField(
        default=dict, help_text="Bank details provided for refund"
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Cancel: {self.transaction.flw_ref}"


class WithdrawalRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", _("Pending")
        PROCESSED = "PROCESSED", _("Processed")
        FAILED = "FAILED", _("Failed")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="withdrawals"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    destination_bank_code = models.CharField(max_length=10)
    destination_account_number = models.CharField(max_length=20)

    reference = models.CharField(max_length=100, unique=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING
    )

    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Withdrawal: {self.user.email} - {self.amount}"


class LedgerEntry(models.Model):
    class EntryType(models.TextChoices):
        CREDIT = "CREDIT", _("Credit")
        DEBIT = "DEBIT", _("Debit")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ledger_entries",
    )
    # Net amount moving into/out of the user's available balance
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    entry_type = models.CharField(max_length=10, choices=EntryType.choices)
    description = models.TextField()

    # Link to the source of the movement
    transaction = models.ForeignKey(
        Transaction,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )
    withdrawal = models.ForeignKey(
        WithdrawalRequest,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ledger_entries",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.email} | {self.entry_type} | {self.amount}"
