# API Reference - Real Estate Pro

## 🔐 Authentication
**Base URL**: `/api/v1/users/`

| Endpoint | Method | Description | Auth |
|---|---|---|---|
| `auth/register/` | POST | Register a new user | None |
| `auth/verify-signup/` | POST | Verify email with OTP | None |
| `auth/login/` | POST | Obtain JWT tokens | None |
| `auth/refresh/` | POST | Refresh JWT access token | None |
| `profile/` | GET/PUT | Manage user profile | JWT |

## 🏠 Properties
**Base URL**: `/api/v1/properties/`

| Endpoint | Method | Description | Auth |
|---|---|---|---|
| `properties/` | GET | List properties (cached) | None |
| `properties/` | POST | Create property (3-5 images) | Owner/Admin |
| `properties/{id}/` | GET | Detailed info + increment views | None |
| `properties/{id}/similar_properties/` | GET | Get 5 similar listings | None |
| `properties/{id}/toggle_favorite/` | POST | Add/Remove from favorites | JWT |

## 🤝 Engagement
| Endpoint | Method | Description | Auth |
|---|---|---|---|
| `reviews/` | POST | Rate and review a property | JWT |
| `tour-requests/` | POST | Request a tour | JWT |
| `tour-requests/{id}/approve/` | POST | Approve a request | Owner |
| `notifications/` | GET | List user notifications | JWT |
| `device-tokens/` | POST | Register device for push | JWT |

## 👑 Admin Operations
| Endpoint | Method | Description | Auth |
|---|---|---|---|
| `admin/owner-requests/` | GET/PUT | Review owner applications | Admin |
| `admin/properties/{id}/ban/` | POST | Ban a property | Admin |
| `analytics/` | GET | Real-time platform stats | Admin/Owner |

---
*Note: Most list endpoints support standard DRF filtering (`?category=RESIDENTIAL`) and ordering (`?ordering=-price`).*
