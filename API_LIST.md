# Real Estate Backend API List

All API endpoints are prefixed with `/api/v1/`.

## 🛡️ Authentication & Account Security
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| POST | `/users/auth/register/` | Start signup, triggers email OTP | No |
| POST | `/users/auth/verify-signup/` | Verify email OTP and create account | No |
| POST | `/users/auth/resend-otp/` | Resend signup email OTP | No |
| POST | `/users/auth/login/` | Get JWT Tokens (Access/Refresh) | No |
| POST | `/users/auth/refresh/` | Refresh Access Token | No |
| POST | `/users/auth/forgot-password/` | Send password reset email OTP | No |
| POST | `/users/auth/reset-password/` | Reset password using email OTP | No |

## 👤 User Profile Management
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| GET | `/users/profile/` | View current user profile | Yes |
| PUT/PATCH | `/users/profile/` | Update profile / Upload Picture | Yes |

## 🏠 Property Owner Workflow (Phone Verified)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| POST | `/users/owner-requests/` | Submit request (Docs + Phone). Sends SMS OTP | Yes |
| POST | `/users/owner-requests/verify/` | Verify SMS OTP to finalize request | Yes |
| POST | `/users/owner-requests/resend/` | Resend SMS OTP (Max 2 times) | Yes |
| GET | `/users/owner-requests/` | Check status of YOUR request | Yes |

## ⚙️ System Administration
*Restricted to accounts with Staff/Superuser privileges.*
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| GET | `/users/admin/users/` | List all system users | Admin |
| POST | `/users/admin/users/` | Create a new user manually | Admin |
| GET/PUT/PATCH/DELETE | `/users/admin/users/{id}/` | Full User Management | Admin |
| GET | `/users/admin/owner-requests/` | List all ownership requests | Admin |
| PATCH | `/users/admin/owner-requests/{id}/` | Approve/Reject a verified request | Admin |

## 🏥 Health & Diagnostics
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| GET | `/health/` | Global Application Health Check | No |
| GET | `/properties/health/` | Properties Service Health | No |

## 📖 Interactive Documentation
- **Swagger Interface**: `/swagger/`
- **Redoc Interface**: `/redoc/`
