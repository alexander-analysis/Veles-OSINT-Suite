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
    draught: float | None = None  # metres
    length_m: float | None = None
    beam_m: float | None = None
    extra: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.mmsi = str(self.mmsi)
        if self.heading is not None and self.heading >= 511:
            self.heading = None
        if self.speed is not None and self.speed >= 102.3:  # AIS "not available"
            self.speed = None
        if self.flag is None:
            self.flag = flag_from_mmsi(self.mmsi)
        self.imo = valid_imo(self.imo)
        self.name = clean_name(self.name)
        self.destination = clean_name(self.destination) if self.destination else self.destination


IMO_PLACEHOLDERS = {"1234567"}  # passes the check digit by coincidence, typed into thousands of transponders


def valid_imo(value) -> str | None:
    """Seven digits with a correct check digit, else None - placeholders (0, 1, 1234567, 999999999) are shared by
    hundreds of transponders and would otherwise glue unrelated hulls together."""
    if value is None:
        return None
    digits = str(value).strip().upper().removeprefix("IMO").strip()
    if len(digits) != 7 or not digits.isdigit() or len(set(digits)) == 1 or digits in IMO_PLACEHOLDERS:
        return None
    if sum(int(d) * w for d, w in zip(digits[:6], (7, 6, 5, 4, 3, 2))) % 10 != int(digits[6]):
        return None
    return digits


def clean_name(value) -> str | None:
    """AIS 6-bit text padding ('@') and stray whitespace stripped; empty -> None."""
    if value is None:
        return None
    text = " ".join(str(value).replace("@", " ").split()).strip(" -_.")
    return text or None
