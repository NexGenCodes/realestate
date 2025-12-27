# Real Estate Pro - Advanced Property Management System

A production-grade Real Estate platform built with Django REST Framework, featuring geospatial search, real-time-ready notifications, and enterprise-level caching.

## 🚀 Core Features

### 🏢 Property Management
- **Geospatial Discovery**: Search properties using coordinates (PostGIS) with distance-based filtering.
- **Advanced Filtering**: Narrow down listings by price range, area, rating, and owner verification status.
- **Smart Recommendations**: A Built-in engine that suggests similar properties based on category, price proximity (±20%), and average rating.
- **Engagement Stats**: Automatic tracking of `views_count` and cached `average_rating`.

### 🛡️ User & Owner Ecosystem
- **Email-Centric Auth**: Secure JWT-based authentication using email as the unique identifier.
- **Owner Verification Flow**: Structured two-stage verification (Request -> Admin Review -> Promotion) with ID document handling (Cloudinary).
- **Saved Searches**: Users can save their search criteria to receive future alerts.

### 🔔 Professional Messaging
- **Notification Backbone**: Multi-platform `DeviceToken` registration for push notifications.
- **Automated Triggers**: 
    - Owners receive **Emails + In-app Alerts** for new tour requests and reviews.
    - Users receive status updates when their owner requests are approved/rejected.
- **Admin Alerts**: System monitors email credits and notifies admins if thresholds are low.

## 🛠️ Tech Stack & Architecture

- **Backend**: Python 3.11 / Django 5.2 / DRF
- **Database**: PostgreSQL with **PostGIS** for high-performance spatial queries.
- **Caching**: **Redis** integrated via `django-redis` for list view acceleration and OTP storage.
- **Task Queue**: **Celery** for background email delivery and credit monitoring.
- **Media**: **Cloudinary** for secure document and property image storage.
- **Documentation**: Automatic OpenAPI (Swagger) generation via `drf-yasg`.

## 📈 Performance & Scaling
- **Indexing**: Optimized B-tree indexes on `price`, `status`, and `views_count`.
- **Spatial Indexing**: GIST indexes on `location` for sub-second proximity searches.
- **Caching Strategy**: Intelligent invalidation that clears list caches only on property mutations (Create/Update/Delete).

## 🧪 Verification
The platform is hardened with a consolidated test suite following DRF best practices:
```bash
docker-compose run --rm web python -m pytest tests/tests_consolidated.py
```

## 📖 API Documentation
For a full list of endpoints and parameters, please refer to [API_REFERENCE.md](./API_REFERENCE.md) or visit `/swagger/` on a running instance.
