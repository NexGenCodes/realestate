from django_filters import rest_framework as filters
from .models import Property


class PropertyFilter(filters.FilterSet):
    min_price = filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="price", lookup_expr="lte")
    min_area = filters.NumberFilter(field_name="area_sqft", lookup_expr="gte")
    max_area = filters.NumberFilter(field_name="area_sqft", lookup_expr="lte")
    min_rating = filters.NumberFilter(field_name="average_rating", lookup_expr="gte")
    is_verified_owner = filters.BooleanFilter(field_name="owner__is_verified_owner")

    class Meta:
        model = Property
        fields = [
            "category",
            "property_type",
            "status",
            "bedrooms",
            "bathrooms",
            "min_price",
            "max_price",
            "min_area",
            "max_area",
            "min_rating",
            "is_verified_owner",
        ]
