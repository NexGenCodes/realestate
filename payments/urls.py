from django.urls import path
from .views import (
    WebhookView,
    TransactionListView,
    CancelTransactionView,
    OwnerWithdrawalView,
    AdminWithdrawalView,
    WalletView,
    VerifyBankAccountView,
    InitiatePaymentView,
)

urlpatterns = [
    path("webhook/", WebhookView.as_view(), name="payment-webhook"),
    path("transactions/", TransactionListView.as_view(), name="transaction-list"),
    path(
        "transactions/<int:pk>/cancel/",
        CancelTransactionView.as_view(),
        name="transaction-cancel",
    ),
    path("withdraw/owner/", OwnerWithdrawalView.as_view(), name="owner-withdrawal"),
    path("withdraw/admin/", AdminWithdrawalView.as_view(), name="admin-withdrawal"),
    path("wallet/", WalletView.as_view(), name="wallet"),
    path("verify-account/", VerifyBankAccountView.as_view(), name="verify-account"),
    path("initiate/", InitiatePaymentView.as_view(), name="payment-initiate"),
]
