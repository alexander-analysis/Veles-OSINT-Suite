"""Shared AIS vocabulary: the position record every source produces, MMSI -> flag, ship types."""

from dataclasses import dataclass, field
from datetime import datetime

from app.data.mid import MID_TO_ISO

# AIS ship-type codes (ITU-R M.1371), first digit groups
SHIP_TYPES = {
    2: "Wing in ground", 3: "Fishing", 4: "High-speed craft", 5: "Special craft", 6: "Passenger",
    7: "Cargo", 8: "Tanker", 9: "Other",
}
SHIP_TYPE_EXACT = {
    30: "Fishing", 31: "Towing", 32: "Towing (large)", 33: "Dredging", 34: "Diving", 35: "Military",
    36: "Sailing", 37: "Pleasure craft", 50: "Pilot vessel", 51: "Search and rescue", 52: "Tug",
    53: "Port tender", 54: "Anti-pollution", 55: "Law enforcement", 58: "Medical transport",
}
NAV_STATUS = {
    0: "underway", 1: "at_anchor", 2: "not_under_command", 3: "restricted_manoeuvrability",
    4: "constrained_by_draught", 5: "moored", 6: "aground", 7: "fishing", 8: "sailing",
    11: "towing_astern", 12: "pushing_ahead", 14: "ais_sart", 15: "undefined",
}


def ship_type_name(code: int | None) -> str | None:
    if code is None:
        return None
    if code in SHIP_TYPE_EXACT:
        return SHIP_TYPE_EXACT[code]
    return SHIP_TYPES.get(code // 10)


def flag_from_mmsi(mmsi: str | int) -> str:
    """ISO-3166 alpha-2 flag state from the MMSI's Maritime Identification Digits ('XX' if unknown)."""
    return MID_TO_ISO.get(str(mmsi)[:3], "XX")


@dataclass
class AISPosition:
    """One position report, normalised across sources.  Metadata fields are optional."""

    mmsi: str
    lat: float
    lon: float
    timestamp: datetime
    source: str
    speed: float | None = None  # knots
    course: float | None = None  # degrees
    heading: float | None = None  # degrees (511 = unavailable in AIS -> None)
    nav_status: str | None = None
    signal_quality: int | None = None
    name: str | None = None
    imo: str | None = None
    call_sign: str | None = None
    ship_type: str | None = None
    flag: str | None = None
    destination: str | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.mmsi = str(self.mmsi)
        if self.heading is not None and self.heading >= 511:
            self.heading = None
        if self.speed is not None and self.speed >= 102.3:  # AIS "not available"
            self.speed = None
        if self.flag is None:
            self.flag = flag_from_mmsi(self.mmsi)
        if self.imo in ("0", 0, ""):
            self.imo = None
