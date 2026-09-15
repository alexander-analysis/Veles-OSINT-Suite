"""ADS-B lookups (keyless): adsb.lol by registration / hex, OpenSky anonymous state vectors."""

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

from app.utils.logger import logger
from app.utils.time import from_unix_seconds, utcnow

log = logger.bind(component="adsb")

ADSB_LOL = "https://api.adsb.lol/v2"
OPENSKY = "https://opensky-network.org/api/states/all"
UA = {"User-Agent": "VELES-OSINT/1.0 (sanctions research)"}
MIN_INTERVAL = 1.6  # adsb.lol answers 429 to bursts; one request every ~1.5 s is tolerated
_last_call = 0.0
_lock = asyncio.Lock()


@dataclass
class Sighting:
    registration: str | None
    icao_hex: str | None
    timestamp: datetime
    latitude: float | None
    longitude: float | None
    altitude_ft: float | None
    ground_speed_kts: float | None
    heading: float | None
    callsign: str | None
    squawk: str | None
    on_ground: bool | None
    source: str
    aircraft_type: str | None = None
    raw: dict[str, Any] | None = None


def _parse_adsb_lol(ac: dict[str, Any], now_ms: int | None) -> Sighting:
    alt = ac.get("alt_baro")
    on_ground = alt == "ground"
    seen = ac.get("seen_pos") or ac.get("seen") or 0
    ts = from_unix_seconds((now_ms or 0) / 1000 - float(seen)) if now_ms else utcnow()
    return Sighting(
        registration=(ac.get("r") or "").strip() or None,
        icao_hex=(ac.get("hex") or "").lower() or None,
        timestamp=ts,
        latitude=ac.get("lat"),
        longitude=ac.get("lon"),
        altitude_ft=None if on_ground or alt is None else float(alt),
        ground_speed_kts=ac.get("gs"),
        heading=ac.get("track"),
        callsign=(ac.get("flight") or "").strip() or None,
        squawk=ac.get("squawk"),
        on_ground=on_ground,
        source="adsb_lol",
        aircraft_type=ac.get("t"),
        raw={k: ac.get(k) for k in ("desc", "ownOp", "dbFlags", "category", "emergency", "nav_altitude_mcp") if ac.get(k) is not None},
    )


async def _get(url: str, params: dict[str, Any] | None = None) -> httpx.Response:
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        async with httpx.AsyncClient(timeout=30, headers=UA) as client:
            response = await client.get(url, params=params)
        _last_call = time.monotonic()
    return response


async def lookup_registration(registration: str) -> list[Sighting]:
    """Current position(s) for a registration - empty when the airframe is not transmitting."""
    response = await _get(f"{ADSB_LOL}/reg/{registration}")
    if response.status_code == 429:
        log.warning("adsb.lol rate limited")
        await asyncio.sleep(5)
        return []
    if response.status_code != 200 or not response.text.strip().startswith("{"):
        return []
    data = response.json()
    return [_parse_adsb_lol(ac, data.get("now")) for ac in data.get("ac", []) or []]


async def lookup_hexes(hexes: list[str]) -> list[Sighting]:
    """adsb.lol accepts a comma-separated list of Mode S codes."""
    if not hexes:
        return []
    response = await _get(f"{ADSB_LOL}/hex/{','.join(h.lower() for h in hexes[:50])}")
    if response.status_code != 200 or not response.text.strip().startswith("{"):
        return []
    data = response.json()
    return [_parse_adsb_lol(ac, data.get("now")) for ac in data.get("ac", []) or []]


async def opensky_states(hexes: list[str]) -> list[Sighting]:
    """Anonymous OpenSky state vectors for up to ~100 Mode S codes (400 requests / day budget)."""
    if not hexes:
        return []
    params = [("icao24", h.lower()) for h in hexes[:100]]
    async with httpx.AsyncClient(timeout=30, headers=UA) as client:
        response = await client.get(OPENSKY, params=params)
    if response.status_code != 200:
        log.debug("opensky {}", response.status_code)
        return []
    data = response.json() or {}
    out = []
    for s in data.get("states") or []:
        # icao24, callsign, origin_country, time_position, last_contact, lon, lat, baro_altitude, on_ground, velocity, true_track, vertical_rate, sensors, geo_altitude, squawk, spi, position_source
        out.append(
            Sighting(
                registration=None,
                icao_hex=s[0],
                timestamp=from_unix_seconds(s[4] or data.get("time") or 0),
                latitude=s[6],
                longitude=s[5],
                altitude_ft=round(s[7] * 3.28084) if s[7] is not None else None,
                ground_speed_kts=round(s[9] * 1.94384, 1) if s[9] is not None else None,
                heading=s[10],
                callsign=(s[1] or "").strip() or None,
                squawk=s[14],
                on_ground=bool(s[8]),
                source="opensky",
                raw={"origin_country": s[2]},
            )
        )
    return out
