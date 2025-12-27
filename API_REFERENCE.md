# API Reference Guide

This guide provides a detailed reference for all API endpoints in the Real Estate Pro platform. For interactive testing, visit the [Swagger UI](/swagger/) on your local instance.

## 🔗 Endpoint Index

### 1. System Health
- `GET /api/health-check/`: System status and database connectivity check.

### 2. Authentication & Identity
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/users/auth/register/` | POST | Register a new account. |
| `/api/v1/users/auth/verify-signup/` | POST | Verify account with OTP. |
| `/api/v1/users/auth/login/` | POST | Obtain JWT access/refresh tokens. |
| `/api/v1/users/auth/forgot-password/` | POST | Trigger password reset email. |

### 3. Property Management (Geospatial)
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/properties/` | GET | List properties. Supports `lat`, `lon`, `dist` (meters) filters. |
| `/api/v1/properties/` | POST | Create a new listing (Auto-geocodes administrative data). |
| `/api/v1/properties/analytics/` | GET | Owner dashboard for view counts and engagement metrics. |

### 4. Payments & Financial Ledger
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/payments/initiate/` | POST | Request Flutterwave payment configuration for a property. |
| `/api/v1/payments/wallet/` | GET | View available/clearing balance and ledger activity. |
| `/api/v1/payments/withdraw/owner/` | POST | Payout released funds to a verified bank account. |
| `/api/v1/payments/transactions/<id>/cancel/` | POST | Initiate 7-day refund/cancellation workflow. |

### 5. Engagement & Notifications
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/users/profile/` | GET/PUT | Manage user personal and bank profile. |
| `/api/v1/users/notifications/` | GET | Retrieve push notification history. |
| `/api/v1/users/device-tokens/` | POST | Register FCM tokens for real-time alerts. |

---
> [!NOTE]
> All financial transactions are subject to a 7-day escrow period.
> Proximity searches use meter-based precision via PostGIS `distance_lte` logic.
