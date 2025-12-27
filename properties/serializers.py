import logging
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from .models import (
    Property,
    PropertyImage,
    Favorite,
    Amenity,
    PropertyReview,
    TourRequest,
    PropertyReport,
)

logger = logging.getLogger(__name__)


class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage


class AmenitySerializer(serializers.ModelSerializer):
    class Meta:
        model = Amenity
        fields = ["id", "name", "icon"]


class PropertyReviewSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source="user.first_name", read_only=True)

    class Meta:
        model = PropertyReview
        fields = [
            "id",
            "property",
            "user",
            "user_name",
            "rating",
            "comment",
            "created_at",
        ]
        read_only_fields = ["user", "created_at"]


class TourRequestSerializer(serializers.ModelSerializer):
    requester_name = serializers.CharField(source="requester.email", read_only=True)
    property_title = serializers.CharField(source="property.title", read_only=True)

    class Meta:
        model = TourRequest
        fields = [
            "id",
            "property",
            "property_title",
            "requester",
            "requester_name",
            "slot",
            "status",
            "message",
            "created_at",
        ]
        read_only_fields = ["requester", "status", "created_at"]


class PropertySerializer(serializers.ModelSerializer):
    """
    Serializer for Property using a standard ModelSerializer with Manual Geo handling
    or just use GeoModelSerializer if simple.
    We'll use a standard ModelSerializer but return/accept the point data.
    """

    owner_name = serializers.CharField(source="owner.email", read_only=True)
    category_display = serializers.CharField(
        source="get_category_display", read_only=True
    )
    amenity_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )
    amenities = AmenitySerializer(many=True, read_only=True)
    reviews = PropertyReviewSerializer(many=True, read_only=True)
    uploaded_images = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text="Array of objects: {'url': '...', 'is_featured': true/false}. Must be 3-5.",
    )
    is_favorited = serializers.SerializerMethodField()

    class Meta:
        model = Property
        fields = [
            "id",
            "owner",
            "owner_name",
            "category",
            "category_display",
            "title",
            "description",
            "latitude",
            "longitude",
            "address_text",
            "price",
            "property_type",
            "status",
            "bedrooms",
            "bathrooms",
            "area_sqft",
            "amenities",
            "amenity_ids",
            "video_url",
            "views_count",
            "average_rating",
            "reviews",
            "images",
            "uploaded_images",
            "is_favorited",
            "is_banned",
            "appeal_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "owner",
            "status",
            "is_banned",
            "appeal_status",
            "views_count",
            "average_rating",
            "images",
            "reviews",
        ]

    def get_is_favorited(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Favorite.objects.filter(user=request.user, property=obj).exists()
        return False

    def validate_uploaded_images(self, value):
        if not (3 <= len(value) <= 5):
            raise serializers.ValidationError(
                _("Each property must have between 3 and 5 images.")
            )
        return value

    def create(self, validated_data):
        uploaded_images = validated_data.pop("uploaded_images", [])
        amenity_ids = validated_data.pop("amenity_ids", [])
        property_obj = Property.objects.create(**validated_data)

        if amenity_ids:
            property_obj.amenities.set(amenity_ids)

        for img_data in uploaded_images:
            PropertyImage.objects.create(
                property=property_obj,
                image_url=img_data.get("url"),
                is_featured=img_data.get("is_featured", False),
            )

        logger.info(
            f"Property created: {property_obj.id} with {len(uploaded_images)} images."
        )
        return property_obj

    def update(self, instance, validated_data):
        uploaded_images = validated_data.pop("uploaded_images", None)
        amenity_ids = validated_data.pop("amenity_ids", None)

        if amenity_ids is not None:
            instance.amenities.set(amenity_ids)

        # update property fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if uploaded_images is not None:
            # Replace images
            instance.images.all().delete()
            for img_data in uploaded_images:
                PropertyImage.objects.create(
                    property=instance,
                    image_url=img_data.get("url"),
                    is_featured=img_data.get("is_featured", False),
                )
            logger.info(
                f"Property {instance.id} images updated. New count: {len(uploaded_images)}."
            )

        logger.info(f"Property updated: {instance.id}")
        return instance


class FavoriteSerializer(serializers.ModelSerializer):
    property_details = PropertySerializer(source="property", read_only=True)

    class Meta:
        model = Favorite
        fields = ["id", "user", "property", "property_details", "created_at"]
        read_only_fields = ["user"]


class PropertyReportSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)

    class Meta:
        model = PropertyReport
        fields = ["id", "property", "user", "user_email", "reason", "created_at"]
        read_only_fields = ["user", "created_at"]
