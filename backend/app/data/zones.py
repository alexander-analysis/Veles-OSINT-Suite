"""Monitoring zones and shipping lanes / chokepoints as GeoJSON-style polygons.

Polygons are deliberately coarse (bounding shapes of the relevant sea areas):
they drive *alerts for analyst review*, not legal geofences.  Coordinates are
``[lon, lat]`` rings.

Zone ``kind``: ``sanctions_zone`` (tagged with the authorities whose
restrictive measures apply), ``war_zone``, ``piracy_zone``.
Lane ``choke_point``: True for narrow passages where transit monitoring is
most valuable.
"""


def _box(lon_min: float, lat_min: float, lon_max: float, lat_max: float) -> list[list[float]]:
    return [[lon_min, lat_min], [lon_max, lat_min], [lon_max, lat_max], [lon_min, lat_max], [lon_min, lat_min]]


ZONES: list[dict] = [
    {"name": "Crimea & Sea of Azov", "kind": "sanctions_zone", "authorities": ["EU", "OFAC"], "context": "Occupied territory - port access bans; war zone",
     "ring": [[32.4, 44.3], [36.6, 44.3], [39.3, 45.3], [39.3, 47.4], [34.8, 47.4], [32.4, 46.0], [32.4, 44.3]]},
    {"name": "Russian Black Sea coast", "kind": "sanctions_zone", "authorities": ["EU", "OFAC"], "context": "Novorossiysk/Tuapse/Taman export terminals (price cap)",
     "ring": _box(36.5, 43.3, 40.2, 45.3)},
    {"name": "Gulf of Finland - Russian terminals", "kind": "sanctions_zone", "authorities": ["EU", "OFAC"], "context": "Primorsk / Ust-Luga / Vysotsk approaches (price cap, shadow fleet)",
     "ring": _box(27.6, 59.55, 30.4, 60.75)},
    {"name": "Kola Bay / Murmansk", "kind": "sanctions_zone", "authorities": ["EU", "OFAC"], "context": "Arctic STS crude transfers",
     "ring": _box(32.5, 68.8, 33.8, 69.5)},
    {"name": "Iranian Gulf waters", "kind": "sanctions_zone", "authorities": ["OFAC", "EU", "UN"], "context": "Kharg / Assaluyeh / Bandar Abbas - Iranian petroleum export",
     "ring": [[48.5, 30.6], [50.0, 30.6], [52.6, 28.4], [55.5, 27.4], [57.5, 26.2], [57.5, 25.4], [56.2, 25.9], [54.0, 26.4], [51.5, 27.5], [49.5, 29.6], [48.5, 30.6]]},
    {"name": "DPRK waters", "kind": "sanctions_zone", "authorities": ["UN", "OFAC", "EU"], "context": "UNSCR 2375/2397 - STS transfers to/from DPRK vessels prohibited",
     "ring": [[124.4, 37.7], [125.6, 37.7], [126.1, 38.7], [128.5, 38.8], [130.0, 41.5], [130.9, 42.5], [129.5, 42.6], [127.8, 40.0], [126.0, 39.8], [124.4, 38.5], [124.4, 37.7]]},
    {"name": "Syrian coast", "kind": "sanctions_zone", "authorities": ["OFAC", "EU"], "context": "Latakia / Tartus / Banias",
     "ring": _box(35.3, 34.5, 36.2, 36.0)},
    {"name": "Cuban waters", "kind": "sanctions_zone", "authorities": ["OFAC"], "context": "Comprehensive US programme",
     "ring": [[-85.2, 21.6], [-84.6, 23.3], [-81.0, 23.6], [-79.5, 22.2], [-74.0, 20.6], [-74.5, 19.6], [-77.9, 19.4], [-82.0, 19.9], [-85.2, 21.6]]},
    {"name": "Venezuelan coast", "kind": "sanctions_zone", "authorities": ["OFAC"], "context": "PDVSA export terminals",
     "ring": _box(-71.8, 9.9, -61.5, 12.6)},
    {"name": "Libyan coast", "kind": "sanctions_zone", "authorities": ["UN", "EU"], "context": "UN arms embargo - illicit petroleum exports (UNSCR 2146)",
     "ring": _box(10.0, 30.2, 25.2, 33.6)},
    {"name": "Red Sea / Gulf of Aden", "kind": "war_zone", "authorities": ["UN"], "context": "Houthi attacks on shipping; Yemen arms embargo",
     "ring": [[41.0, 20.0], [40.0, 15.0], [42.5, 12.3], [44.0, 11.6], [51.0, 11.6], [51.0, 14.6], [46.0, 15.0], [43.5, 17.5], [41.0, 20.0]]},
    {"name": "Black Sea war zone", "kind": "war_zone", "authorities": [], "context": "Naval mines, corridor traffic - Ukrainian ports",
     "ring": _box(28.6, 44.8, 33.6, 46.7)},
    {"name": "Gulf of Guinea", "kind": "piracy_zone", "authorities": [], "context": "Piracy / kidnapping hotspot",
     "ring": _box(-6.0, -2.0, 9.5, 6.5)},
    {"name": "Somali Basin", "kind": "piracy_zone", "authorities": [], "context": "Piracy resurgence",
     "ring": _box(44.0, -4.0, 60.0, 14.0)},
    {"name": "Laconian Gulf STS area", "kind": "sanctions_zone", "authorities": ["EU"], "context": "Known ship-to-ship hub for Russian-origin crude",
     "ring": _box(22.4, 36.2, 23.2, 36.8)},
    {"name": "Malaysia EOPL STS area", "kind": "sanctions_zone", "authorities": ["OFAC"], "context": "Eastern OPL anchorage - Iranian/Venezuelan crude relabelling",
     "ring": _box(104.1, 1.1, 104.9, 1.6)},
]

LANES: list[dict] = [
    {"name": "Danish Straits (Great Belt / Oresund)", "choke_point": True, "ring": _box(10.4, 54.4, 13.2, 56.5)},
    {"name": "Gulf of Finland corridor", "choke_point": True, "ring": _box(23.0, 59.3, 27.6, 60.4)},
    {"name": "Bosporus", "choke_point": True, "ring": _box(28.85, 40.95, 29.25, 41.35)},
    {"name": "Dardanelles", "choke_point": True, "ring": _box(26.1, 39.95, 26.8, 40.5)},
    {"name": "Kerch Strait", "choke_point": True, "ring": _box(36.3, 44.9, 36.9, 45.5)},
    {"name": "Strait of Gibraltar", "choke_point": True, "ring": _box(-6.1, 35.7, -5.2, 36.2)},
    {"name": "Dover Strait", "choke_point": True, "ring": _box(0.9, 50.7, 2.1, 51.3)},
    {"name": "Suez Canal", "choke_point": True, "ring": _box(32.2, 29.8, 32.7, 31.4)},
    {"name": "Bab-el-Mandeb", "choke_point": True, "ring": _box(42.8, 12.1, 43.8, 13.2)},
    {"name": "Strait of Hormuz", "choke_point": True, "ring": _box(55.4, 25.6, 57.2, 27.0)},
    {"name": "Strait of Malacca", "choke_point": True, "ring": [[98.0, 6.0], [100.5, 6.0], [104.2, 1.0], [104.2, 0.6], [102.0, 1.7], [98.0, 4.0], [98.0, 6.0]]},
    {"name": "Panama Canal", "choke_point": True, "ring": _box(-80.1, 8.85, -79.45, 9.45)},
    {"name": "Taiwan Strait", "choke_point": True, "ring": _box(117.5, 23.0, 121.0, 26.0)},
    {"name": "Cape of Good Hope route", "choke_point": False, "ring": _box(17.0, -36.0, 21.0, -33.5)},
]


def zones_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [z["ring"]]},
             "properties": {"name": z["name"], "kind": z["kind"], "authorities": z["authorities"], "context": z["context"]}}
            for z in ZONES
        ],
    }


def lanes_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [lane["ring"]]},
             "properties": {"name": lane["name"], "choke_point": lane["choke_point"]}}
            for lane in LANES
        ],
    }
