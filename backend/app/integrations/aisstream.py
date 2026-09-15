"""aisstream.io - global AIS over WebSocket (free API key).

The stream is long-lived: a consumer task keeps the newest report per MMSI in
memory and the bot drains it on every poll.  Static-data messages supply
name / IMO / call sign / type.
"""

import asyncio
import json
from datetime import datetime

import websockets

from app.integrations.ais_common import AISPosition, NAV_STATUS, ship_type_name
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="maritime")

URL = "wss://stream.aisstream.io/v0/stream"
SOURCE = "aisstream"
POSITION_TYPES = ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport")


class AISStreamClient:
    def __init__(self, api_key: str, bounding_boxes: list | None = None) -> None:
        self.api_key = api_key
        # [[[lat_min, lon_min], [lat_max, lon_max]], ...] - default: whole world
        self.bounding_boxes = bounding_boxes or [[[-90, -180], [90, 180]]]
        self.latest: dict[str, AISPosition] = {}
        self.static: dict[str, dict] = {}
        self.connected = False
        self.messages = 0
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="aisstream")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()

    def drain(self) -> list[AISPosition]:
        positions = list(self.latest.values())
        self.latest.clear()
        return positions

    def _handle(self, raw: str) -> None:
        message = json.loads(raw)
        meta = message.get("MetaData", {})
        mmsi = str(meta.get("MMSI", ""))
        kind = message.get("MessageType")
        self.messages += 1
        if kind == "ShipStaticData":
            data = message["Message"]["ShipStaticData"]
            self.static[mmsi] = {
                "name": (data.get("Name") or "").strip() or None,
                "imo": str(data["ImoNumber"]) if data.get("ImoNumber") else None,
                "call_sign": (data.get("CallSign") or "").strip() or None,
                "ship_type": ship_type_name(data.get("Type")),
                "destination": (data.get("Destination") or "").strip() or None,
            }
            return
        if kind not in POSITION_TYPES:
            return
        data = message["Message"][kind]
        try:
            timestamp = datetime.strptime(meta.get("time_utc", "")[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            timestamp = utcnow()
        static = self.static.get(mmsi, {})
        self.latest[mmsi] = AISPosition(
            mmsi=mmsi,
            lat=meta.get("latitude", data.get("Latitude")),
            lon=meta.get("longitude", data.get("Longitude")),
            timestamp=timestamp,
            source=SOURCE,
            speed=data.get("Sog"),
            course=data.get("Cog"),
            heading=data.get("TrueHeading"),
            nav_status=NAV_STATUS.get(data.get("NavigationalStatus")),
            signal_quality=80,
            name=(meta.get("ShipName") or "").strip() or static.get("name"),
            imo=static.get("imo"),
            call_sign=static.get("call_sign"),
            ship_type=static.get("ship_type"),
            destination=static.get("destination"),
        )

    async def _run(self) -> None:
        delay = 5
        while True:
            try:
                async with websockets.connect(URL, ping_interval=30, ping_timeout=90, max_size=None) as socket:
                    await socket.send(json.dumps({"APIKey": self.api_key, "BoundingBoxes": self.bounding_boxes}))
                    self.connected = True
                    delay = 5
                    log.info("aisstream connected ({} bounding box(es))", len(self.bounding_boxes))
                    async for raw in socket:
                        try:
                            self._handle(raw)
                        except Exception as exc:  # noqa: BLE001
                            log.debug("aisstream: bad message - {}", exc)
            except asyncio.CancelledError:
                self.connected = False
                raise
            except Exception as exc:  # noqa: BLE001
                self.connected = False
                log.warning("aisstream error: {} - reconnecting in {}s", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
