"""AISHub - aggregated AIS for members who contribute a feed (free username).

``https://data.aishub.net/ws.php?username=...&format=1&output=json`` returns
``[{"ERROR": false, ...}, [records...]]``.  Disabled unless AISHUB_USERNAME is set.
"""

from datetime import datetime, timezone

import httpx

from app.integrations.ais_common import AISPosition, NAV_STATUS, ship_type_name
from app.utils.logger import logger

log = logger.bind(component="maritime")

SOURCE = "ais_hub"


class AISHubClient:
    def __init__(self, username: str, bbox: tuple[float, float, float, float] | None = None) -> None:
        self.username = username
        self.bbox = bbox  # (min_lat, min_lon, max_lat, max_lon)

    async def fetch_positions(self) -> list[AISPosition]:
        params = {"username": self.username, "format": 1, "output": "json", "compress": 0}
        if self.bbox:
            params.update({"latmin": self.bbox[0], "lonmin": self.bbox[1], "latmax": self.bbox[2], "lonmax": self.bbox[3]})
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get("https://data.aishub.net/ws.php", params=params)
            response.raise_for_status()
            payload = response.json()
        header, rows = payload[0], payload[1] if len(payload) > 1 else []
        if header.get("ERROR"):
            raise RuntimeError(f"AISHub error: {header.get('ERROR_MESSAGE')}")
        positions = []
        for row in rows:
            positions.append(
                AISPosition(
                    mmsi=str(row["MMSI"]),
                    lat=float(row["LATITUDE"]),
                    lon=float(row["LONGITUDE"]),
                    timestamp=datetime.fromtimestamp(int(row["TIME"]), tz=timezone.utc).replace(tzinfo=None),
                    source=SOURCE,
                    speed=float(row["SOG"]) if row.get("SOG") is not None else None,
                    course=float(row["COG"]) if row.get("COG") is not None else None,
                    heading=float(row["HEADING"]) if row.get("HEADING") is not None else None,
                    nav_status=NAV_STATUS.get(int(row["NAVSTAT"])) if row.get("NAVSTAT") is not None else None,
                    signal_quality=70,
                    name=(row.get("NAME") or "").strip() or None,
                    imo=str(row["IMO"]) if row.get("IMO") else None,
                    call_sign=(row.get("CALLSIGN") or "").strip() or None,
                    ship_type=ship_type_name(int(row["TYPE"])) if row.get("TYPE") else None,
                    destination=(row.get("DEST") or "").strip() or None,
                )
            )
        log.info("ais_hub: {} positions", len(positions))
        return positions
