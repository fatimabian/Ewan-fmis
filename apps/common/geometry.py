"""Small, dependency free geometry helpers (the database is MySQL, so no GIS extension)."""
from math import asin, cos, radians, sin, sqrt

from apps.farm_parcels.rosario_boundary import ROSARIO_BOUNDARY

EARTH_RADIUS_M = 6_371_000


def point_in_ring(latitude, longitude, ring):
    """Ray casting test against a ring of (latitude, longitude) pairs."""
    inside = False
    previous_latitude, previous_longitude = ring[-1]
    for current_latitude, current_longitude in ring:
        if (current_latitude > latitude) != (previous_latitude > latitude):
            crossing = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < crossing:
                inside = not inside
        previous_latitude, previous_longitude = current_latitude, current_longitude
    return inside


def is_in_rosario(latitude, longitude):
    """True when the point falls inside the Rosario municipal outline."""
    return point_in_ring(latitude, longitude, ROSARIO_BOUNDARY)


def haversine_m(first, second):
    """Great circle distance in metres between two (latitude, longitude) points."""
    lat1, lon1, lat2, lon2 = map(radians, (*first, *second))
    half = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(half))


def polygon_area_ha(points):
    """Area in hectares of a small (latitude, longitude) polygon, using a local flat projection."""
    if len(points) < 3:
        return 0.0
    mean_latitude = radians(sum(lat for lat, _ in points) / len(points))
    projected = [
        (radians(lon) * EARTH_RADIUS_M * cos(mean_latitude), radians(lat) * EARTH_RADIUS_M)
        for lat, lon in points
    ]
    twice_area = sum(
        x1 * y2 - x2 * y1
        for (x1, y1), (x2, y2) in zip(projected, projected[1:] + projected[:1])
    )
    return abs(twice_area) / 2 / 10_000
