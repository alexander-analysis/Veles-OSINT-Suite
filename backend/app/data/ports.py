"""Curated port reference data for port-call detection and port intelligence.

Coordinates are approximate berth/anchorage centres; ``radius_km`` is the
detection radius.  ``risk_level`` reflects sanctions exposure of the facility
(Russian crude/product export terminals, Iranian, DPRK, Syrian, Cuban and
Venezuelan terminals, occupied-Ukraine ports) - it is an analytic flag, not a
legal determination.  Extend freely; the list is loaded once at startup.
"""

PORTS: list[dict] = [
    # ---- Baltic / Gulf of Finland (Digitraffic coverage) -------------------
    {"name": "Primorsk", "unlocode": "RUPRI", "country": "RU", "lat": 60.336, "lon": 28.700, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "Major Russian crude export terminal (price-cap regime)"},
    {"name": "Ust-Luga", "unlocode": "RUULU", "country": "RU", "lat": 59.680, "lon": 28.400, "radius_km": 8, "risk_level": "high", "sanctioned_facility": True, "note": "Russian crude/product/LNG export hub"},
    {"name": "St Petersburg", "unlocode": "RULED", "country": "RU", "lat": 59.900, "lon": 30.200, "radius_km": 10, "risk_level": "high", "sanctioned_facility": False, "note": "Russian Baltic port"},
    {"name": "Vysotsk", "unlocode": "RUVYS", "country": "RU", "lat": 60.620, "lon": 28.560, "radius_km": 4, "risk_level": "high", "sanctioned_facility": True, "note": "Russian product/LNG terminal"},
    {"name": "Vyborg", "unlocode": "RUVYB", "country": "RU", "lat": 60.705, "lon": 28.730, "radius_km": 4, "risk_level": "medium", "sanctioned_facility": False, "note": ""},
    {"name": "Kaliningrad", "unlocode": "RUKGD", "country": "RU", "lat": 54.700, "lon": 20.450, "radius_km": 8, "risk_level": "high", "sanctioned_facility": False, "note": "Russian exclave port"},
    {"name": "Helsinki", "unlocode": "FIHEL", "country": "FI", "lat": 60.155, "lon": 24.950, "radius_km": 6, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Kotka", "unlocode": "FIKTK", "country": "FI", "lat": 60.440, "lon": 26.930, "radius_km": 5, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Hamina", "unlocode": "FIHMN", "country": "FI", "lat": 60.540, "lon": 27.190, "radius_km": 4, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Porvoo (Skoldvik)", "unlocode": "FIPRV", "country": "FI", "lat": 60.310, "lon": 25.540, "radius_km": 4, "risk_level": "safe", "sanctioned_facility": False, "note": "Neste refinery"},
    {"name": "Turku", "unlocode": "FITKU", "country": "FI", "lat": 60.440, "lon": 22.230, "radius_km": 5, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Tallinn (Muuga)", "unlocode": "EETLL", "country": "EE", "lat": 59.500, "lon": 24.950, "radius_km": 7, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Riga", "unlocode": "LVRIX", "country": "LV", "lat": 57.030, "lon": 24.090, "radius_km": 7, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Klaipeda", "unlocode": "LTKLJ", "country": "LT", "lat": 55.700, "lon": 21.120, "radius_km": 6, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Gdansk", "unlocode": "PLGDN", "country": "PL", "lat": 54.400, "lon": 18.690, "radius_km": 8, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Stockholm", "unlocode": "SESTO", "country": "SE", "lat": 59.320, "lon": 18.100, "radius_km": 6, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    # ---- Black Sea / Azov -----------------------------------------------------
    {"name": "Novorossiysk", "unlocode": "RUNVS", "country": "RU", "lat": 44.710, "lon": 37.790, "radius_km": 8, "risk_level": "high", "sanctioned_facility": True, "note": "Russian crude export (CPC/Sheskharis)"},
    {"name": "Tuapse", "unlocode": "RUTUA", "country": "RU", "lat": 44.095, "lon": 39.070, "radius_km": 5, "risk_level": "high", "sanctioned_facility": True, "note": "Russian product terminal"},
    {"name": "Taman", "unlocode": "RUTAM", "country": "RU", "lat": 45.120, "lon": 36.680, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "Russian bulk/oil terminal"},
    {"name": "Sevastopol", "unlocode": "UASVP", "country": "UA", "lat": 44.610, "lon": 33.520, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "Occupied Crimea - EU/OFAC port bans"},
    {"name": "Feodosia", "unlocode": "UAFEO", "country": "UA", "lat": 45.030, "lon": 35.390, "radius_km": 5, "risk_level": "high", "sanctioned_facility": True, "note": "Occupied Crimea"},
    {"name": "Kerch", "unlocode": "UAKER", "country": "UA", "lat": 45.350, "lon": 36.480, "radius_km": 5, "risk_level": "high", "sanctioned_facility": True, "note": "Occupied Crimea"},
    {"name": "Berdyansk", "unlocode": "UABER", "country": "UA", "lat": 46.740, "lon": 36.770, "radius_km": 5, "risk_level": "high", "sanctioned_facility": True, "note": "Occupied - grain export concerns"},
    {"name": "Mariupol", "unlocode": "UAMPW", "country": "UA", "lat": 47.060, "lon": 37.510, "radius_km": 5, "risk_level": "high", "sanctioned_facility": True, "note": "Occupied"},
    {"name": "Odesa", "unlocode": "UAODS", "country": "UA", "lat": 46.490, "lon": 30.740, "radius_km": 8, "risk_level": "medium", "sanctioned_facility": False, "note": "War-zone corridor"},
    {"name": "Constanta", "unlocode": "ROCND", "country": "RO", "lat": 44.150, "lon": 28.650, "radius_km": 8, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Istanbul (Ambarli)", "unlocode": "TRAMR", "country": "TR", "lat": 40.970, "lon": 28.680, "radius_km": 8, "risk_level": "medium", "sanctioned_facility": False, "note": ""},
    # ---- Arctic / Pacific Russia ----------------------------------------------
    {"name": "Murmansk", "unlocode": "RUMMK", "country": "RU", "lat": 69.000, "lon": 33.070, "radius_km": 10, "risk_level": "high", "sanctioned_facility": True, "note": "Arctic crude STS hub (Kola Bay)"},
    {"name": "Kozmino", "unlocode": "RUKOZ", "country": "RU", "lat": 42.720, "lon": 133.070, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "ESPO crude export terminal"},
    {"name": "Vladivostok", "unlocode": "RUVVO", "country": "RU", "lat": 43.100, "lon": 131.900, "radius_km": 8, "risk_level": "high", "sanctioned_facility": False, "note": ""},
    {"name": "Nakhodka", "unlocode": "RUNJK", "country": "RU", "lat": 42.800, "lon": 132.880, "radius_km": 6, "risk_level": "high", "sanctioned_facility": False, "note": ""},
    # ---- Middle East -----------------------------------------------------------
    {"name": "Kharg Island", "unlocode": "IRKHK", "country": "IR", "lat": 29.230, "lon": 50.310, "radius_km": 10, "risk_level": "high", "sanctioned_facility": True, "note": "Main Iranian crude export terminal"},
    {"name": "Bandar Abbas", "unlocode": "IRBND", "country": "IR", "lat": 27.150, "lon": 56.210, "radius_km": 10, "risk_level": "high", "sanctioned_facility": True, "note": ""},
    {"name": "Bandar Imam Khomeini", "unlocode": "IRBKM", "country": "IR", "lat": 30.430, "lon": 49.080, "radius_km": 8, "risk_level": "high", "sanctioned_facility": True, "note": ""},
    {"name": "Assaluyeh", "unlocode": "IRASA", "country": "IR", "lat": 27.470, "lon": 52.620, "radius_km": 8, "risk_level": "high", "sanctioned_facility": True, "note": "South Pars condensate/LPG"},
    {"name": "Fujairah", "unlocode": "AEFJR", "country": "AE", "lat": 25.150, "lon": 56.380, "radius_km": 10, "risk_level": "medium", "sanctioned_facility": False, "note": "Bunkering / STS hub"},
    {"name": "Latakia", "unlocode": "SYLTK", "country": "SY", "lat": 35.520, "lon": 35.770, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": ""},
    {"name": "Tartus", "unlocode": "SYTTS", "country": "SY", "lat": 34.900, "lon": 35.870, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": ""},
    {"name": "Banias", "unlocode": "SYBAN", "country": "SY", "lat": 35.180, "lon": 35.930, "radius_km": 5, "risk_level": "high", "sanctioned_facility": True, "note": "Oil terminal"},
    {"name": "Hodeidah", "unlocode": "YEHOD", "country": "YE", "lat": 14.830, "lon": 42.920, "radius_km": 8, "risk_level": "high", "sanctioned_facility": False, "note": "Houthi-controlled"},
    # ---- East Asia -------------------------------------------------------------
    {"name": "Nampo", "unlocode": "KPNAM", "country": "KP", "lat": 38.720, "lon": 125.400, "radius_km": 8, "risk_level": "high", "sanctioned_facility": True, "note": "DPRK - UNSCR 2397"},
    {"name": "Wonsan", "unlocode": "KPWON", "country": "KP", "lat": 39.160, "lon": 127.440, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "DPRK"},
    {"name": "Chongjin", "unlocode": "KPCHO", "country": "KP", "lat": 41.770, "lon": 129.830, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "DPRK"},
    {"name": "Rajin", "unlocode": "KPRAJ", "country": "KP", "lat": 42.230, "lon": 130.290, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "DPRK"},
    {"name": "Shanghai", "unlocode": "CNSHA", "country": "CN", "lat": 30.630, "lon": 122.070, "radius_km": 15, "risk_level": "safe", "sanctioned_facility": False, "note": "Yangshan"},
    {"name": "Singapore", "unlocode": "SGSIN", "country": "SG", "lat": 1.260, "lon": 103.800, "radius_km": 15, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    # ---- Americas / Europe ----------------------------------------------------
    {"name": "Havana", "unlocode": "CUHAV", "country": "CU", "lat": 23.140, "lon": -82.350, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "Cuba - comprehensive US programme"},
    {"name": "Matanzas", "unlocode": "CUQMA", "country": "CU", "lat": 23.050, "lon": -81.560, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "Oil terminal"},
    {"name": "Jose Terminal", "unlocode": "VEJOS", "country": "VE", "lat": 10.100, "lon": -64.860, "radius_km": 8, "risk_level": "high", "sanctioned_facility": True, "note": "PDVSA crude export"},
    {"name": "Puerto La Cruz", "unlocode": "VEPLC", "country": "VE", "lat": 10.230, "lon": -64.620, "radius_km": 6, "risk_level": "high", "sanctioned_facility": True, "note": "PDVSA"},
    {"name": "Rotterdam", "unlocode": "NLRTM", "country": "NL", "lat": 51.950, "lon": 4.050, "radius_km": 15, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Antwerp", "unlocode": "BEANR", "country": "BE", "lat": 51.280, "lon": 4.330, "radius_km": 10, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Hamburg", "unlocode": "DEHAM", "country": "DE", "lat": 53.530, "lon": 9.950, "radius_km": 10, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
    {"name": "Houston", "unlocode": "USHOU", "country": "US", "lat": 29.730, "lon": -95.020, "radius_km": 15, "risk_level": "safe", "sanctioned_facility": False, "note": ""},
]
