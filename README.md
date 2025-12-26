# Real Estate Backend API

A robust, production-ready backend for a Real Estate platform, built with Django REST Framework.

## 🚀 Features

- **Unified Messaging**: Centralized hub for Email (Resend) notifications.
- **Cloudinary Storage**: Optimized media storage for profile pictures and documents.
- **Literal URL Persistence**: Direct absolute URLs stored in the database for instant frontend access.
- **Robust Auth**: OTP-based signup, password reset, and secure JWT-based session management.
- **Admin Audit**: Detailed logging and tracking for all critical operations.
- **System Health**: Active monitoring and low-credit alerts for communication providers.

## 🛠 Tech Stack

- **Framework**: Django 5.x & Django REST Framework
- **Storage**: Cloudinary (via `django-cloudinary-storage`)
- **Messaging**: Anymail (Resend)
- **Task Queue**: Celery & Redis
- **Security**: JWT (SimpleJWT), OTP, Atomic Transactions
- **Documentation**: Swagger/OpenAPI (drf-yasg)

## 📖 API Documentation

The API is fully documented using Swagger and Redoc.

- **Swagger UI**: `/swagger/`
- **Redoc UI**: `/redoc/`

## 🔗 API Reference

### Authentication
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/users/auth/register/` | `POST` | Register a new user & trigger OTP email. |
| `/api/v1/users/auth/verify-signup/` | `POST` | Verify email OTP and create user account. |
| `/api/v1/users/auth/resend-otp/` | `POST` | Resend verification OTP to email. |
| `/api/v1/users/auth/login/` | `POST` | Login and obtain JWT tokens. |
| `/api/v1/users/auth/refresh/` | `POST` | Refresh session using refresh token. |
| `/api/v1/users/auth/forgot-password/` | `POST` | Trigger password reset OTP. |
| `/api/v1/users/auth/reset-password/` | `POST` | Set new password using OTP. |

### User Profile
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/users/profile/` | `GET`, `PATCH`, `PUT` | Manage authenticated user profile. |

### Owner Requests
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/users/owner-requests/` | `GET`, `POST` | List or submit ownership verification requests. |

### Admin Operations
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/users/admin/users/` | `CRUD` | Manage all system users. |
| `/api/v1/users/admin/owner-requests/` | `GET`, `PATCH`, `PUT` | Review and approve/reject owner requests. |

### System Health
| Endpoint | Method | Description |
| :--- | :--- | :--- |
| `/api/v1/properties/health/` | `GET` | Get system status and heartbeat. |

## 🛠 Local Setup

1. **Environment**: Copy `.env.example` to `.env` and fill in credentials.
2. **Migrations**: `python manage.py migrate`
3. **Runserver**: `python manage.py runserver`
4. **Celery**: `celery -A config worker -l info`
