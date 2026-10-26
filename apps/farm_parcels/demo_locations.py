from collections import defaultdict

from .rosario_boundary import ROSARIO_BOUNDARY


# Published barangay reference points. Demo records are deliberately kept close
# to their barangay centre so a barangay filter never appears elsewhere.
ROSARIO_BARANGAY_CENTERS = {
    "Alupay": (13.8404, 121.2922), "Antipolo": (13.7080, 121.3096),
    "Bagong Pook": (13.8402, 121.2216), "Balibago": (13.8512, 121.2855),
    "Barangay A": (13.8457, 121.2104), "Barangay B": (13.8461, 121.2065),
    "Barangay C": (13.8467, 121.2032), "Barangay D": (13.8440, 121.2035),
    "Barangay E": (13.8415, 121.2047), "Bayawang": (13.7944, 121.2798),
    "Baybayin": (13.8277, 121.2589), "Bulihan": (13.7967, 121.2351),
    "Cahigam": (13.8021, 121.2501), "Calantas": (13.7340, 121.3129),
    "Colongan": (13.8114, 121.1762), "Itlugan": (13.8190, 121.2036),
    "Leviste": (13.7694, 121.2868), "Lumbangan": (13.8122, 121.2649),
    "Maalas-As": (13.8112, 121.2122), "Mabato": (13.8144, 121.2913),
    "Mabunga": (13.7810, 121.2924), "Macalamcam A": (13.8551, 121.3046),
    "Macalamcam B": (13.8606, 121.3265), "Malaya": (13.8535, 121.1720),
    "Maligaya": (13.8182, 121.2742), "Marilag": (13.8562, 121.1764),
    "Masaya": (13.8383, 121.1852), "Matamis": (13.7216, 121.3305),
    "Mavalor": (13.8177, 121.2315), "Mayuro": (13.7944, 121.2623),
    "Namuco": (13.8382, 121.2036), "Namunga": (13.8431, 121.1978),
    "Nasi": (13.7699, 121.3127), "Natu": (13.8420, 121.2683),
    "Palakpak": (13.7079, 121.3320), "Pinagsibaan": (13.8438, 121.3141),
    "Putingkahoy": (13.8349, 121.3227), "Quilib": (13.8603, 121.2002),
    "Salao": (13.8578, 121.3455), "San Carlos": (13.8478, 121.2475),
    "San Ignacio": (13.8335, 121.1764), "San Isidro": (13.8074, 121.3152),
    "San Jose": (13.8419, 121.2329), "San Roque": (13.8518, 121.2039),
    "Santa Cruz": (13.8599, 121.1853), "Timbugan": (13.8095, 121.1869),
    "Tiquiwan": (13.8284, 121.2399), "Tulos": (13.7231, 121.2971),
}


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


def rosario_demo_coordinates_for_barangays(barangays):
    """Return stable synthetic points near each record's actual barangay."""
    occurrences = defaultdict(int)
    points = []
    for barangay in barangays:
        centre = ROSARIO_BARANGAY_CENTERS.get(barangay)
        if centre is None:
            points.extend(rosario_demo_coordinates(1))
            continue
        occurrences[barangay] += 1
        index = occurrences[barangay]
        latitude = centre[0] + (_halton(index, 2) - 0.5) * 0.0036
        longitude = centre[1] + (_halton(index, 3) - 0.5) * 0.0048
        if not _inside_rosario(latitude, longitude):
            latitude, longitude = centre
        points.append(f"{latitude:.7f},{longitude:.7f}")
    return points
