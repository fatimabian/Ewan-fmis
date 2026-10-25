from .rosario_boundary import ROSARIO_BOUNDARY


def _halton(index, base):
    result = 0.0
    fraction = 1.0
    while index:
        fraction /= base
        result += fraction * (index % base)
        index //= base
    return result


def _inside_rosario(latitude, longitude):
    inside = False
    previous = ROSARIO_BOUNDARY[-1]
    for current in ROSARIO_BOUNDARY:
        previous_latitude, previous_longitude = previous
        current_latitude, current_longitude = current
        crosses = (current_latitude > latitude) != (previous_latitude > latitude)
        if crosses:
            edge_longitude = (
                (previous_longitude - current_longitude)
                * (latitude - current_latitude)
                / (previous_latitude - current_latitude)
                + current_longitude
            )
            if longitude < edge_longitude:
                inside = not inside
        previous = current
    return inside


def rosario_demo_coordinates(count):
    """Return stable, well-distributed synthetic points inside Rosario."""
    if count <= 0:
        return []
    latitudes = [point[0] for point in ROSARIO_BOUNDARY]
    longitudes = [point[1] for point in ROSARIO_BOUNDARY]
    south, north = min(latitudes), max(latitudes)
    west, east = min(longitudes), max(longitudes)
    points = []
    candidate = 1
    while len(points) < count:
        latitude = south + (north - south) * _halton(candidate, 2)
        longitude = west + (east - west) * _halton(candidate, 3)
        candidate += 1
        if _inside_rosario(latitude, longitude):
            points.append(f"{latitude:.7f},{longitude:.7f}")
    return points
