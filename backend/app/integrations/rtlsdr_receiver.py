"""Local AIS receiver (RTL-SDR dongle) via NMEA over UDP.

``rtl_ais -n`` (or AIS-catcher ``-u 127.0.0.1 10110``) decodes VHF AIS into
``!AIVDM`` sentences and sends them over UDP.  This listener decodes them
with ``pyais`` and keeps the newest report per MMSI, so VELES needs no
special driver bindings - any NMEA-over-UDP source works (also dAISy, an
external NMEA feed forwarded with ``socat``, ...).

Source tag: ``rtl_sdr`` - the highest-confidence position source (no third
party in the loop).
"""

import asyncio

from app.integrations.ais_common import AISPosition, NAV_STATUS, ship_type_name
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="maritime")

SOURCE = "rtl_sdr"


class NMEAUDPReceiver:
    def __init__(self, port: int = 10110, host: str = "0.0.0.0") -> None:
        self.host, self.port = host, port
        self.latest: dict[str, AISPosition] = {}
        self.static: dict[str, dict] = {}
        self.sentences = 0
        self.listening = False
        self._transport = None
        self._decoder = None

    async def start(self) -> None:
        if self._transport is not None:
            return
        try:
            from pyais.stream import UDPReceiver  # noqa: F401  - verifies pyais is importable
            import pyais
        except ImportError:
            log.warning("pyais not installed - RTL-SDR/NMEA receiver disabled")
            return
        self._decoder = pyais
        loop = asyncio.get_running_loop()
        self._transport, _ = await loop.create_datagram_endpoint(lambda: _Protocol(self), local_addr=(self.host, self.port))
        self.listening = True
        log.info("NMEA UDP receiver listening on {}:{}", self.host, self.port)

    def stop(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None
            self.listening = False

    def drain(self) -> list[AISPosition]:
        positions = list(self.latest.values())
        self.latest.clear()
        return positions

    def feed(self, line: str) -> None:
        """Decode one NMEA sentence (multi-part messages are reassembled by pyais)."""
        line = line.strip()
        if not line.startswith(("!AIVDM", "!AIVDO")):
            return
        self.sentences += 1
        try:
            decoded = self._decoder.decode(line).asdict()
        except Exception:  # noqa: BLE001 - fragment of a multipart message or checksum error
            return
        mmsi = str(decoded.get("mmsi", ""))
        msg_type = decoded.get("msg_type")
        if msg_type == 5 or msg_type == 24:
            entry = self.static.setdefault(mmsi, {})
            for key, field in (("name", "shipname"), ("call_sign", "callsign"), ("destination", "destination")):
                if decoded.get(field):
                    entry[key] = str(decoded[field]).strip("@ ") or None
            if decoded.get("imo"):
                entry["imo"] = str(decoded["imo"])
            if decoded.get("ship_type") is not None:
                code = decoded["ship_type"]
                entry["ship_type"] = ship_type_name(int(code) if not hasattr(code, "value") else int(code.value))
            return
        if msg_type not in (1, 2, 3, 18, 19) or decoded.get("lat") is None:
            return
        status = decoded.get("status")
        status_code = int(status.value) if hasattr(status, "value") else status
        static = self.static.get(mmsi, {})
        self.latest[mmsi] = AISPosition(
            mmsi=mmsi,
            lat=float(decoded["lat"]),
            lon=float(decoded["lon"]),
            timestamp=utcnow(),
            source=SOURCE,
            speed=decoded.get("speed"),
            course=decoded.get("course"),
            heading=decoded.get("heading"),
            nav_status=NAV_STATUS.get(status_code) if status_code is not None else None,
            signal_quality=100,
            **{k: static.get(k) for k in ("name", "imo", "call_sign", "ship_type", "destination")},
        )


class _Protocol(asyncio.DatagramProtocol):
    def __init__(self, receiver: NMEAUDPReceiver) -> None:
        self.receiver = receiver

    def datagram_received(self, data: bytes, _addr) -> None:
        for line in data.decode("ascii", errors="ignore").splitlines():
            self.receiver.feed(line)


class NMEATCPClient(NMEAUDPReceiver):
    """Same decoder fed from a TCP NMEA stream (e.g. Kystverket 153.44.253.27:5631, or AIS-catcher's TCP output).

    Reconnects with back-off; ``source`` is tagged ``nmea_tcp`` unless overridden.
    """

    def __init__(self, host: str, port: int, source: str = "nmea_tcp") -> None:
        super().__init__(port=port, host=host)
        self.source_name = source
        self.connected = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        try:
            import pyais
        except ImportError:
            log.warning("pyais not installed - NMEA TCP client disabled")
            return
        self._decoder = pyais
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name=f"nmea-tcp-{self.host}")

    def stop(self) -> None:
        if self._task:
            self._task.cancel()
        self.listening = False

    def feed(self, line: str) -> None:
        super().feed(line)
        # re-tag the newest report with this stream's source name
        mmsi = line and next(reversed(self.latest), None)
        if mmsi and self.latest[mmsi].source == SOURCE:
            self.latest[mmsi].source = self.source_name

    async def _run(self) -> None:
        delay = 5
        while True:
            writer = None
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(self.host, self.port), timeout=20)
                self.connected = self.listening = True
                delay = 5
                log.info("NMEA TCP stream connected: {}:{}", self.host, self.port)
                while True:
                    raw = await asyncio.wait_for(reader.readline(), timeout=120)
                    if not raw:
                        raise ConnectionError("stream closed")
                    self.feed(raw.decode("ascii", errors="ignore"))
            except asyncio.CancelledError:
                self.connected = self.listening = False
                raise
            except Exception as exc:  # noqa: BLE001
                self.connected = self.listening = False
                log.warning("NMEA TCP {}:{} error: {} - reconnecting in {}s", self.host, self.port, exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 300)
            finally:
                if writer is not None:
                    writer.close()
