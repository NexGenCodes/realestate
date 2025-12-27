import logging
from django.db import transaction, models
from django.db.models import Avg
from django.utils import timezone
from .models import Property, PropertyReport, Favorite, TourRequest, PropertyReview
from shared.messaging import (
    notify_owner_property_status_change,
    check_email_credits,
    notify_owner_new_tour_request,
)

logger = logging.getLogger(__name__)


class PropertyService:
    @staticmethod
    @transaction.atomic
    def mark_as_rented(property_obj, user):
        if property_obj.status != Property.Status.AVAILABLE:
            raise ValueError("Only available properties can be marked as rented.")

        property_obj.status = Property.Status.RENTED
        property_obj.save()

        logger.info(
            f"[PROPERTY] Property {property_obj.id} marked as RENTED by owner {user.email}"
        )
        notify_owner_property_status_change(
            property_obj.owner.email, property_obj.title, "RENTED"
        )
        check_email_credits()
        return property_obj

    @staticmethod
    @transaction.atomic
    def mark_as_sold(property_obj, user):
        if property_obj.status != Property.Status.AVAILABLE:
            raise ValueError("Only available properties can be marked as sold.")

        property_obj.status = Property.Status.SOLD
        property_obj.save()

        logger.info(
            f"[PROPERTY] Property {property_obj.id} marked as SOLD by owner {user.email}"
        )
        notify_owner_property_status_change(
            property_obj.owner.email, property_obj.title, "SOLD"
        )
        check_email_credits()
        return property_obj

    @staticmethod
    def toggle_favorite(property_obj, user):
        favorite, created = Favorite.objects.get_or_create(
            user=user, property=property_obj
        )
        if not created:
            favorite.delete()
            logger.info(
                f"[FAVORITE] User {user.email} removed property {property_obj.id} from favorites."
            )
            return False

        logger.info(
            f"[FAVORITE] User {user.email} added property {property_obj.id} to favorites."
        )
        return True

    @staticmethod
    @transaction.atomic
    def ban_property(property_obj, reason, admin_user):
        property_obj.is_banned = True
        property_obj.ban_reason = reason
        property_obj.status = Property.Status.BANNED
        property_obj.save()
        logger.warning(
            f"Admin {admin_user.email} BANNED property {property_obj.id}. Reason: {reason}"
        )
        return property_obj

    @staticmethod
    @transaction.atomic
    def appeal_ban(property_obj, appeal_text, user):
        if not property_obj.is_banned:
            raise ValueError("Only banned properties can be appealed.")

        property_obj.appeal_status = Property.AppealStatus.PENDING
        property_obj.appeal_text = appeal_text
        property_obj.save()
        logger.info(
            f"Owner {user.email} submitted an APPEAL for property {property_obj.id}."
        )
        return property_obj

    @staticmethod
    @transaction.atomic
    def lift_ban(property_obj, admin_user):
        property_obj.is_banned = False
        property_obj.status = Property.Status.AVAILABLE
        property_obj.appeal_status = Property.AppealStatus.RESOLVED
        property_obj.save()
        logger.info(
            f"Admin {admin_user.email} LIFTED BAN on property {property_obj.id}."
        )
        return property_obj


class ReportingService:
    @staticmethod
    @transaction.atomic
    def report_property(property_obj, user, reason):
        if property_obj.owner == user:
            raise ValueError("Owners cannot report their own property.")

        if PropertyReport.objects.filter(property=property_obj, user=user).exists():
            raise ValueError("You have already reported this property.")

        report = PropertyReport.objects.create(
            property=property_obj, user=user, reason=reason
        )

        # Automatic ban logic
        report_count = property_obj.reports.count()
        if report_count >= 5 and not property_obj.is_banned:
            PropertyService.ban_property(
                property_obj,
                f"Automatically banned after {report_count} reports.",
                user,  # In this case it's the 5th reporter who triggers it
            )

        return report


class ReviewService:
    @staticmethod
    @transaction.atomic
    def create_review(property_obj, user, rating, comment):
        review = PropertyReview.objects.create(
            property=property_obj, user=user, rating=rating, comment=comment
        )
        # Update property average rating
        avg_rating = PropertyReview.objects.filter(property=property_obj).aggregate(
            Avg("rating")
        )["rating__avg"]
        property_obj.average_rating = avg_rating or 0
        property_obj.save()

        # Notify Owner
        from users.models import Notification

        Notification.objects.create(
            user=property_obj.owner,
            title="New Review",
            body=f"{user.email} reviewed your property '{property_obj.title}'.",
        )

        logger.info(f"[REVIEW] User {user.email} reviewed property {property_obj.id}")
        return review


class TourRequestService:
    @staticmethod
    @transaction.atomic
    def create_tour_request(property_obj, requester, slot, message):
        instance = TourRequest.objects.create(
            property=property_obj,
            requester=requester,
            slot=slot,
            message=message,
        )

        # Notify Owner
        notify_owner_new_tour_request(
            owner_email=property_obj.owner.email,
            property_title=property_obj.title,
            requester_email=requester.email,
            slot=slot,
        )

        logger.info(
            f"[TOUR] User {requester.email} requested tour for property {property_obj.id}"
        )
        return instance

    @staticmethod
    @transaction.atomic
    def update_status(tour_request, status_value, user):
        tour_request.status = status_value
        tour_request.save()

        logger.info(
            f"[TOUR] Tour request {tour_request.id} status updated to {status_value} by {user.email}"
        )
        return tour_request
