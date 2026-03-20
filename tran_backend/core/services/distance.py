import math

# Earth radius in km (WGS84)
EARTH_RADIUS_KM = 6371.0


def haversine_km(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    """
    Calculate great-circle distance between two points (Haversine formula).
    Returns distance in kilometres.
    """
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.asin(math.sqrt(a))

    return EARTH_RADIUS_KM * c
