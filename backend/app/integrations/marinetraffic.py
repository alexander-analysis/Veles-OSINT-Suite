"""MarineTraffic API (paid; PS07 "vessel positions in a predefined area / bounding box").

Docs: https://servicedocs.marinetraffic.com/ - the JSONO protocol returns a
list of dicts keyed by field name.  Disabled unless MARINETRAFFIC_API_KEY is set.
"""

from datetime import datetime

import httpx

from app.integrations.ais_common import AISPosition, NAV_STATUS, ship_type_name
from app.utils.logger import logger

log = logger.bind(component="maritime")

SOURCE = "marinetraffic"


class MarineTrafficClient:
    def __init__(self, api_key: str, bbox: tuple[float, float, float, float] | None = None, timespan_minutes: int = 10) -> None:
        self.api_key = api_key
        self.bbox = bbox  # (min_lat, min_lon, max_lat, max_lon)
        self.timespan = timespan_minutes

    def _url(self) -> str:
        base = f"https://services.marinetraffic.com/api/exportvessels/v:8/{self.api_key}/protocol:jsono/timespan:{self.timespan}/msgtype:extended"
        if self.bbox:
            min_lat, min_lon, max_lat, max_lon = self.bbox
            base += f"/MINLAT:{min_lat}/MAXLAT:{max_lat}/MINLON:{min_lon}/MAXLON:{max_lon}"
        return base

    async def fetch_positions(self) -> list[AISPosition]:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(self._url())
            response.raise_for_status()
            rows = response.json()
        if isinstance(rows, dict) and "errors" in rows:
            raise RuntimeError(f"MarineTraffic error: {rows['errors']}")
        positions = []
        for row in rows:
            try:
                timestamp = datetime.strptime(row["TIMESTAMP"], "%Y-%m-%dT%H:%M:%S")
            except (KeyError, ValueError):
                continue
            positions.append(
                AISPosition(
                    mmsi=str(row["MMSI"]),
                    lat=float(row["LAT"]),
                    lon=float(row["LON"]),
                    timestamp=timestamp,
                    source=SOURCE,
                    speed=float(row["SPEED"]) / 10 if row.get("SPEED") else None,
                    course=float(row["COURSE"]) if row.get("COURSE") else None,
                    heading=float(row["HEADING"]) if row.get("HEADING") else None,
                    nav_status=NAV_STATUS.get(int(row["STATUS"])) if row.get("STATUS") else None,
                    signal_quality=95,
                    name=row.get("SHIPNAME"),
                    imo=str(row["IMO"]) if row.get("IMO") else None,
                    call_sign=row.get("CALLSIGN"),
                    ship_type=ship_type_name(int(row["SHIPTYPE"])) if row.get("SHIPTYPE") else None,
                    flag=row.get("FLAG"),
                    destination=row.get("DESTINATION"),
                )
            )
        log.info("marinetraffic: {} positions", len(positions))
        return positions
