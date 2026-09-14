"""Fintraffic Digitraffic - open AIS for the Baltic / Finnish waters (no key needed).

REST: ``/api/ais/v1/locations`` (positions, GeoJSON) and ``/api/ais/v1/vessels``
(static data: name, IMO, call sign, type, destination).  The API insists on a
``Digitraffic-User`` header and gzip - httpx sends gzip by default.
"""

from datetime import timedelta

import httpx

from app.integrations.ais_common import AISPosition, NAV_STATUS, ship_type_name
from app.utils.logger import logger
from app.utils.time import from_unix_ms, utcnow

log = logger.bind(component="maritime")

BASE_URL = "https://meri.digitraffic.fi/api/ais/v1"
HEADERS = {"Digitraffic-User": "VELES-OSINT/0.1 (github.com/alexander-analysis/Veles-OSINT-Suite)"}
SOURCE = "digitraffic"


class DigitrafficClient:
    def __init__(self, metadata_ttl_minutes: int = 10) -> None:
        self._metadata: dict[str, dict] = {}
        self._metadata_at = None
        self._ttl = timedelta(minutes=metadata_ttl_minutes)

    async def _refresh_metadata(self, client: httpx.AsyncClient) -> None:
        if self._metadata_at and utcnow() - self._metadata_at < self._ttl:
            return
        response = await client.get(f"{BASE_URL}/vessels")
        response.raise_for_status()
        self._metadata = {str(v["mmsi"]): v for v in response.json()}
        self._metadata_at = utcnow()
        log.debug("digitraffic: {} vessel metadata records", len(self._metadata))

    async def fetch_positions(self, max_age_minutes: int = 30) -> list[AISPosition]:
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            await self._refresh_metadata(client)
            response = await client.get(f"{BASE_URL}/locations")
            response.raise_for_status()
            features = response.json().get("features", [])

        cutoff = utcnow() - timedelta(minutes=max_age_minutes)
        positions = []
        for feature in features:
            props = feature.get("properties", {})
            lon, lat = feature["geometry"]["coordinates"]
            timestamp = from_unix_ms(props.get("timestampExternal", 0))
            if timestamp < cutoff:
                continue
            mmsi = str(props["mmsi"])
            meta = self._metadata.get(mmsi, {})
            positions.append(
                AISPosition(
                    mmsi=mmsi,
                    lat=lat,
                    lon=lon,
                    timestamp=timestamp,
                    source=SOURCE,
                    speed=props.get("sog"),
                    course=props.get("cog") if props.get("cog") != 360 else None,
                    heading=props.get("heading"),
                    nav_status=NAV_STATUS.get(props.get("navStat")),
                    signal_quality=90 if props.get("posAcc") else 70,
                    name=(meta.get("name") or "").strip() or None,
                    imo=str(meta["imo"]) if meta.get("imo") else None,
                    call_sign=(meta.get("callSign") or "").strip() or None,
                    ship_type=ship_type_name(meta.get("shipType")),
                    destination=(meta.get("destination") or "").strip() or None,
                    extra={"draught_dm": meta.get("draught")},
                )
            )
        log.info("digitraffic: {} positions ({} fresh)", len(features), len(positions))
        return positions
