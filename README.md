# Real Estate Pro - Advanced Property Management System

A production-grade Real Estate platform built with Django REST Framework, featuring geospatial search, real-time-ready notifications, and enterprise-level caching.

## 🚀 Core Features

### 🏢 Property Management
- **Geospatial Discovery**: Search properties using coordinates (PostGIS) with distance-based filtering.
- **Advanced Filtering**: Narrow down listings by price range, area, rating, and owner verification status.
- **Smart Recommendations**: A Built-in engine that suggests similar properties based on category, price proximity (±20%), and average rating.
- **Engagement Stats**: Automatic tracking of `views_count` and cached `average_rating`.

### � Secure Financial Ledger (Flutterwave)
- **Escrow-as-a-Service**: Automated 7-day fund clearing period to protect buyers from fraudulent listings.
- **Immutable Ledger**: Every transaction movement (Escrow -> Released -> Withdrawn) is recorded in an immutable ledger with full audit logs.
- **Automated Payouts**: Owners can verify bank accounts and withdraw released funds directly via the dashboard.
- **Cancellation Workflow**: Standardized 7-day refund policy (98% refund to buyer) with automated property banning on excessive reports/cancellations.

### �🛡️ User & Owner Ecosystem
- **Email-Centric Auth**: Secure JWT-based authentication using email as the unique identifier.
- **Owner Verification Flow**: Structured two-stage verification (Request -> Admin Review -> Promotion) with ID document handling (Cloudinary).
- **Saved Searches**: Users can save their search criteria to receive future alerts.
- **Automated Geocoding**: Automatic population of `city`, `state`, and `country` based on GPS coordinates using `geopy`.

### 🔔 Professional Messaging
- **Notification Backbone**: Multi-platform `DeviceToken` registration for push notifications (FCM).
- **Automated Triggers**: 
    - Owners receive **Push + Email** alerts for new tour requests, reviews, and payments.
    - Users receive status updates when their owner requests are approved/rejected.
- **Admin Alerts**: System monitors email credits and notifies admins if thresholds are low.

## 🛠️ Tech Stack & Architecture

- **Backend**: Python 3.11 / Django 5.2 / DRF
- **Database**: PostgreSQL with **PostGIS** for high-performance spatial queries.
- **Payments**: **Flutterwave Integration** for secure widget-based payments and automated transfers.
- **Caching**: **Redis** integrated via `django-redis` for list view acceleration, OTP storage, and wallet balance caching.
- **Task Queue**: **Celery** for background email delivery, push notifications, and daily escrow releases.
- **Media**: **Cloudinary** for secure document and property image storage.
- **Documentation**: Automatic OpenAPI (Swagger) generation via `drf-yasg`.

## 📈 Performance & Scaling
- **Indexing**: Optimized B-tree indexes on `price`, `status`, and `views_count`.
- **Spatial Indexing**: GIST indexes on `location` for sub-second proximity searches.
- **Caching Strategy**: Intelligent invalidation that clears list caches only on property mutations (Create/Update/Delete).

## 🛠️ Development Setup

The easiest way to get started is by using the provided **Docker Compose** configuration.

### Deployment with Docker
1. Clone the repository.
2. Configure `.env` from `.env.example`.
3. Build and start:
   ```bash
   docker-compose up --build
   ```

## 🧪 Verification
The platform is hardened with a comprehensive test suite covering GIS, Geocoding, and Financial logic:
```bash
docker-compose run --rm web pytest --create-db
```

## 📖 API Documentation
For a full list of over 30 endpoints, please refer to `/swagger/` on a running instance or view the [API Registry](./API_REFERENCE.md).
