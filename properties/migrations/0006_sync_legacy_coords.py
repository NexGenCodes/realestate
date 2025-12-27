from django.db import migrations
from django.contrib.gis.geos import Point


def sync_coords(apps, schema_editor):
    Property = apps.get_model("properties", "Property")
    for prop in Property.objects.all():
        if prop.latitude is not None and prop.longitude is not None:
            # Point(longitude, latitude) - SRID 4326 is standard GPS
            prop.location = Point(float(prop.longitude), float(prop.latitude))
            prop.save()


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0005_property_location"),
    ]

    operations = [
        migrations.RunPython(sync_coords),
    ]
