"""Port-call detection and port intelligence flags.

A vessel that is (nearly) stationary inside a curated port's detection radius
is 'in port'.  The bot opens a ``PortCallEvent`` on arrival and closes it on
departure, computing dwell time and raising flags for sanctioned facilities
and unusual dwell times.
"""

from dataclasses import dataclass
from datetime import datetime

from app.analysis.geospatial import port_containing

ARRIVAL_MAX_SPEED = 1.0  # knots
DEPARTURE_MIN_SPEED = 3.0  # knots


@dataclass
class PortState:
    port: dict
    distance_km: float


def port_for_vessel(vessel) -> PortState | None:
    """The port the vessel is currently inside (regardless of speed)."""
    if vessel.current_position_lat is None:
        return None
    found = port_containing(vessel.current_position_lat, vessel.current_position_lon)
    return PortState(found[0], found[1]) if found else None


def is_arrival(vessel, state: PortState | None) -> bool:
    return state is not None and (vessel.current_speed or 0) <= ARRIVAL_MAX_SPEED


def is_departure(vessel, open_call, state: PortState | None) -> bool:
    """Open call ends when the vessel leaves the radius or is clearly underway again."""
    if state is None or state.port["name"] != open_call.port_name:
        return True
    return (vessel.current_speed or 0) >= DEPARTURE_MIN_SPEED


def port_flags(port: dict, dwell_hours: float | None, unusual_dwell_hours: float, vessel) -> list[str]:
    flags = []
    if port.get("sanctioned_facility"):
        flags.append("sanctioned_facility")
    if port.get("risk_level") == "high":
        flags.append("high_risk_port")
    if dwell_hours is not None and dwell_hours >= unusual_dwell_hours:
        flags.append("unusual_dwell_time")
    if (vessel.sanctioned_status or "clear") != "clear":
        flags.append("vessel_flagged")
    if vessel.flag_state and port.get("country") and vessel.flag_state != port["country"] and port.get("risk_level") == "high" and vessel.flag_state in ("GA", "CM", "SL", "KM", "PW", "CK", "LR", "MH", "PA"):
        flags.append("flag_of_convenience_at_high_risk_port")
    return flags


def predicted_cargo(vessel, port: dict) -> str | None:
    ship_type = (vessel.ship_type or "").lower()
    if "tanker" in ship_type:
        return "crude/products" if port.get("sanctioned_facility") else "petroleum/chemicals"
    if "cargo" in ship_type:
        return "dry bulk/general cargo"
    return None


def dwell_hours(arrival: datetime, departure: datetime) -> float:
    return round((departure - arrival).total_seconds() / 3600, 2)
