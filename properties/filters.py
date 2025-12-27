from django_filters import rest_framework as filters
from django.contrib.gis.geos import Point
from django.contrib.gis.measure import D
from .models import Property


class PropertyFilter(filters.FilterSet):
    min_price = filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = filters.NumberFilter(field_name="price", lookup_expr="lte")
    min_area = filters.NumberFilter(field_name="area_sqft", lookup_expr="gte")
    max_area = filters.NumberFilter(field_name="area_sqft", lookup_expr="lte")
    min_rating = filters.NumberFilter(field_name="average_rating", lookup_expr="gte")
    is_verified_owner = filters.BooleanFilter(field_name="owner__is_verified_owner")
    city = filters.CharFilter(lookup_expr="icontains")
    state = filters.CharFilter(lookup_expr="icontains")
    country = filters.CharFilter(lookup_expr="icontains")

    # PostGIS Proximity Filter (e.g. ?dist=5000&lat=6.5&lon=3.4)
    dist = filters.NumberFilter(method="filter_by_distance")

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
            "city",
            "state",
            "country",
        ]

    def filter_by_distance(self, queryset, name, value):
        lat = self.request.query_params.get("lat")
        lon = self.request.query_params.get("lon")
        if lat and lon and value:
            pnt = Point(float(lon), float(lat), srid=4326)
            return queryset.filter(location__dwithin=(pnt, value))
        return queryset
