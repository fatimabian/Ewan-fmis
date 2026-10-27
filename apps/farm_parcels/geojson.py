def _point_in_ring(latitude, longitude, ring):
    inside = False
    previous_longitude, previous_latitude = ring[-1][:2]
    for coordinate in ring:
        current_longitude, current_latitude = coordinate[:2]
        crosses = (current_latitude > latitude) != (previous_latitude > latitude)
        if crosses:
            boundary_longitude = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < boundary_longitude:
                inside = not inside
        previous_longitude, previous_latitude = current_longitude, current_latitude
    return inside


def point_in_geojson(latitude, longitude, geometry):
    """Test WGS84 latitude/longitude against GeoJSON Polygon/MultiPolygon."""
    if not isinstance(geometry, dict):
        return False
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates if geometry_type == "MultiPolygon" else []
    for polygon in polygons:
        if not polygon or not _point_in_ring(latitude, longitude, polygon[0]):
            continue
        if any(_point_in_ring(latitude, longitude, hole) for hole in polygon[1:]):
            continue
        return True
    return False


def geojson_bounds(geometry):
    """Return Leaflet-style bounds for a WGS84 Polygon/MultiPolygon."""
    if not isinstance(geometry, dict):
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates") or []
    polygons = (
        [coordinates]
        if geometry_type == "Polygon"
        else coordinates
        if geometry_type == "MultiPolygon"
        else []
    )
    points = [
        coordinate
        for polygon in polygons
        for ring in polygon
        for coordinate in ring
        if isinstance(coordinate, (list, tuple)) and len(coordinate) >= 2
    ]
    if not points:
        return None
    try:
        longitudes = [float(point[0]) for point in points]
        latitudes = [float(point[1]) for point in points]
    except (TypeError, ValueError):
        return None
    return [
        [min(latitudes), min(longitudes)],
        [max(latitudes), max(longitudes)],
    ]
