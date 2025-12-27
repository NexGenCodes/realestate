from celery import shared_task
from django.utils import timezone
from datetime import timedelta
from .models import Transaction, TransactionAuditLog, LedgerEntry
from django.db import transaction as db_transaction
from shared import messaging
import logging

logger = logging.getLogger(__name__)


@shared_task
def release_payments():
    """
    Find transactions in CLEARING status older than 7 days and release them.
    This effectively moves money from 'Escrow' to 'Available Balance'.
    """
    from .services import PaymentService  # Avoid circular import

    cutoff_date = timezone.now() - timedelta(days=7)

    with db_transaction.atomic():
        # Logic: Status=CLEARING and created_at <= cutoff
        # Use select_for_update to handle race conditions if task runs multiple times
        transactions = Transaction.objects.select_for_update().filter(
            status=Transaction.Status.CLEARING, created_at__lte=cutoff_date
        )

        count = 0
        for tx in transactions:
            old_status = tx.status
            tx.status = Transaction.Status.RELEASED
            tx.save()

            # Create Ledger Entry for the Owner (CREDIT)
            LedgerEntry.objects.create(
                user=tx.owner,
                amount=tx.owner_amount,
                entry_type=LedgerEntry.EntryType.CREDIT,
                description=f"Released Funds for {tx.property.title} ({tx.flw_ref})",
                transaction=tx,
            )

            # Trigger Notification
            messaging.notify_funds_released(tx)

            # Invalidate Cache for Owner
            PaymentService.invalidate_wallet_cache(tx.owner)

            # Log it
            TransactionAuditLog.objects.create(
                transaction=tx,
                old_status=old_status,
                new_status=tx.status,
                changed_by=None,  # System
                ip_address="CELERY_TASK",
            )
            count += 1

    logger.info(f"[CELERY] Released {count} payments from escrow.")
    return f"Released {count} payments"
