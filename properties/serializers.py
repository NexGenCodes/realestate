from rest_framework import serializers
from .models import Property, PropertyImage, Favorite


class PropertyImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = PropertyImage
        fields = ["id", "image_url", "is_featured", "created_at"]


class PropertySerializer(serializers.ModelSerializer):
    """
    Serializer for Property using a standard ModelSerializer with Manual Geo handling
    or just use GeoModelSerializer if simple.
    We'll use a standard ModelSerializer but return/accept the point data.
    """

    owner_name = serializers.CharField(source="owner.username", read_only=True)
    category_display = serializers.CharField(
        source="get_category_display", read_only=True
    )
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
            "location",
            "address_text",
            "price",
            "property_type",
            "status",
            "bedrooms",
            "bathrooms",
            "area_sqft",
            "images",
            "uploaded_images",
            "is_favorited",
            "is_banned",
            "appeal_status",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["owner", "status", "is_banned", "appeal_status"]

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
        property_obj = Property.objects.create(**validated_data)

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
