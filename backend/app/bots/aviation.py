"""Aviation tracker (ecosystem tier 2) - sanctioned airframes on ADS-B.

OFAC aircraft listings (registration, model, operator, MSN, sometimes the Mode S
code) become watched ``Aircraft`` rows.  adsb.lol is swept by registration in
rotation (one request every ~1.6 s), learned Mode S codes are polled in batches
through adsb.lol and anonymous OpenSky.  Every fix is stored as a sighting and
grouped into flights.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.analysis.geospatial import describe_location
from app.analysis.tier2 import parse_aircraft_remarks, registration_country
from app.database import SessionLocal
from app.integrations import adsb
from app.models.audit import AuditLog
from app.models.sanctions import SanctionsEntity
from app.models.tier2 import Aircraft, AircraftSighting
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="aviation")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("aviation", {})


class AviationBot:
    def __init__(self) -> None:
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}
        self._opensky_calls_today = 0
        self._opensky_day: str | None = None

    def status(self) -> dict[str, Any]:
        return {"last_run": dict(self.last_run), "last_result": self.last_result, "opensky_calls_today": self._opensky_calls_today}

    # ----------------------------------------------------------------- seed
    async def sync_aircraft(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._sync)
        self.last_run["sync"] = utcnow()
        self.last_result["sync"] = result
        log.info("aircraft sync: {}", result)
        return result

    @staticmethod
    def _sync() -> dict[str, Any]:
        with SessionLocal() as db:
            existing = {a.registration: a for a in db.execute(select(Aircraft)).scalars()}
            added = updated = 0
            for entity in db.execute(select(SanctionsEntity).where(SanctionsEntity.entity_type == "aircraft")).scalars():
                parsed = parse_aircraft_remarks(entity.remarks)
                registration = (parsed.get("tail") or entity.name or "").strip().upper()
                if not registration or len(registration) > 20:
                    continue
                row = existing.get(registration)
                if row is None:
                    row = Aircraft(registration=registration, origin="sanctions_seed", created_at=utcnow())
                    db.add(row)
                    existing[registration] = row
                    added += 1
                else:
                    updated += 1
                row.model = (parsed.get("model") or row.model or "")[:100] or None
                row.operator = (parsed.get("operator") or row.operator or "")[:200] or None
                row.manufacturer_serial = (parsed.get("msn") or row.manufacturer_serial or "")[:60] or None
                row.icao_hex = (parsed.get("mode_s") or row.icao_hex or "").lower() or None
                row.country = registration_country(registration)
                row.is_sanctioned = bool(entity.is_active)
                row.sanctioned_entity_id = entity.id
                row.sanctioning_authority = entity.designating_authority
                row.programs = entity.programs
                row.owner = row.owner or (entity.vessel_owner or None)
            db.commit()
            total = db.execute(select(func.count(Aircraft.id))).scalar() or 0
            return {"added": added, "updated": updated, "total": total}

    # ---------------------------------------------------------------- sweep
    async def sweep(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        batch = int(cfg.get("sweep_batch", 120))
        due = await asyncio.to_thread(self._due, batch)
        result = {"checked": 0, "airborne": 0, "sightings": 0, "errors": 0}
        sightings: list[tuple[int, adsb.Sighting]] = []
        for aircraft_id, registration in due:
            try:
                found = await adsb.lookup_registration(registration)
                result["checked"] += 1
                if found:
                    result["airborne"] += 1
                    sightings.extend((aircraft_id, s) for s in found)
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                log.debug("lookup failed for {}: {}", registration, exc)
        result["sightings"] = await asyncio.to_thread(self._store, sightings, [a for a, _ in due])
        self.last_run["sweep"] = utcnow()
        self.last_result["sweep"] = result
        log.info("sweep: {}", result)
        return result

    async def poll_hexes(self) -> dict[str, Any]:
        """Aircraft with a known Mode S code: batched adsb.lol + OpenSky lookups (cheap, frequent)."""
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        with SessionLocal() as db:
            rows = db.execute(select(Aircraft.id, Aircraft.icao_hex).where(Aircraft.icao_hex.is_not(None), Aircraft.watch.is_(True))).all()
        if not rows:
            return {"hexes": 0}
        by_hex = {h.lower(): aid for aid, h in rows}
        hexes = list(by_hex)
        sightings: list[tuple[int, adsb.Sighting]] = []
        for i in range(0, len(hexes), 50):
            try:
                for s in await adsb.lookup_hexes(hexes[i:i + 50]):
                    if s.icao_hex in by_hex:
                        sightings.append((by_hex[s.icao_hex], s))
            except Exception as exc:  # noqa: BLE001
                log.debug("hex batch failed: {}", exc)
        today = utcnow().strftime("%Y-%m-%d")
        if self._opensky_day != today:
            self._opensky_day, self._opensky_calls_today = today, 0
        if self._opensky_calls_today < int(cfg.get("opensky_daily_budget", 300)):
            try:
                self._opensky_calls_today += 1
                for s in await adsb.opensky_states(hexes[:100]):
                    if s.icao_hex in by_hex:
                        sightings.append((by_hex[s.icao_hex], s))
            except Exception as exc:  # noqa: BLE001
                log.debug("opensky failed: {}", exc)
        stored = await asyncio.to_thread(self._store, sightings, [])
        self.last_run["hexes"] = utcnow()
        self.last_result["hexes"] = {"hexes": len(hexes), "sightings": stored}
        return self.last_result["hexes"]

    @staticmethod
    def _due(batch: int) -> list[tuple[int, str]]:
        with SessionLocal() as db:
            rows = db.execute(select(Aircraft.id, Aircraft.registration).where(Aircraft.watch.is_(True)).order_by(Aircraft.last_checked.asc().nulls_first()).limit(batch)).all()
            return [(r.id, r.registration) for r in rows]

    def _store(self, sightings: list[tuple[int, adsb.Sighting]], checked_ids: list[int]) -> int:
        now = utcnow()
        stored = 0
        with SessionLocal() as db:
            if checked_ids:
                for row in db.execute(select(Aircraft).where(Aircraft.id.in_(checked_ids))).scalars():
                    row.last_checked = now
            for aircraft_id, s in sightings:
                aircraft = db.get(Aircraft, aircraft_id)
                if aircraft is None:
                    continue
                if s.icao_hex and not aircraft.icao_hex:
                    aircraft.icao_hex = s.icao_hex
                last = db.execute(select(AircraftSighting).where(AircraftSighting.aircraft_id == aircraft_id).order_by(AircraftSighting.timestamp.desc()).limit(1)).scalar_one_or_none()
                if last and abs((s.timestamp - last.timestamp).total_seconds()) < 120 and last.source == s.source:
                    continue  # same fix
                place = describe_location(s.latitude, s.longitude) if s.latitude is not None and s.longitude is not None else None
                flight_key = f"{aircraft.registration}:{s.timestamp:%Y%m%d}:{(s.callsign or '-').strip()}"
                new_flight = not last or last.flight_key != flight_key
                db.add(AircraftSighting(aircraft_id=aircraft_id, registration=aircraft.registration, icao_hex=s.icao_hex or aircraft.icao_hex, timestamp=s.timestamp, latitude=s.latitude, longitude=s.longitude,
                                        altitude_ft=s.altitude_ft, ground_speed_kts=s.ground_speed_kts, heading=s.heading, callsign=s.callsign, squawk=s.squawk, on_ground=s.on_ground, source=s.source,
                                        nearest_place=(place or "")[:120] or None, flight_key=flight_key, details=s.raw or {}))
                aircraft.last_seen = s.timestamp
                aircraft.last_lat, aircraft.last_lon, aircraft.last_altitude_ft, aircraft.last_callsign = s.latitude, s.longitude, s.altitude_ft, s.callsign
                aircraft.sightings_count = (aircraft.sightings_count or 0) + 1
                stored += 1
                if new_flight and aircraft.is_sanctioned:
                    db.add(AuditLog(action_type="sanctioned_aircraft_airborne", user_id="system", rationale=f"{aircraft.registration} ({aircraft.operator or 'operator unknown'}, {aircraft.model or '?'}) seen {place or 'airborne'} as {s.callsign or 'no callsign'}",
                                    supporting_data={"registration": aircraft.registration, "hex": s.icao_hex, "lat": s.latitude, "lon": s.longitude, "altitude_ft": s.altitude_ft, "source": s.source}, source_systems=["bots.aviation"], created_by="system"))
                    from app import notifications

                    notifications.send_alert("aviation", f"Sanctioned aircraft airborne: {aircraft.registration}", f"{aircraft.operator or ''} {aircraft.model or ''} - {place or ''} - callsign {s.callsign or '-'}", severity="high",
                                             data={"registration": aircraft.registration, "lat": s.latitude, "lon": s.longitude})
            db.commit()
        return stored

    # ------------------------------------------------------------- summary
    @staticmethod
    def summary(db: Session, days: int = 7) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        total = db.execute(select(func.count(Aircraft.id))).scalar() or 0
        with_hex = db.execute(select(func.count(Aircraft.id)).where(Aircraft.icao_hex.is_not(None))).scalar() or 0
        seen = db.execute(select(func.count(Aircraft.id)).where(Aircraft.last_seen >= since)).scalar() or 0
        sightings = db.execute(select(func.count(AircraftSighting.id)).where(AircraftSighting.timestamp >= since)).scalar() or 0
        by_operator = db.execute(select(Aircraft.operator, func.count()).where(Aircraft.last_seen >= since).group_by(Aircraft.operator).order_by(func.count().desc()).limit(8)).all()
        by_country = dict(db.execute(select(Aircraft.country, func.count()).group_by(Aircraft.country)).all())
        recent = db.execute(select(Aircraft).where(Aircraft.last_seen.is_not(None)).order_by(Aircraft.last_seen.desc()).limit(10)).scalars().all()
        return {
            "days": days,
            "aircraft": total,
            "with_mode_s": with_hex,
            "seen_recently": seen,
            "sightings": sightings,
            "by_operator": [{"operator": o or "unknown", "aircraft": n} for o, n in by_operator],
            "by_country": by_country,
            "recent": [{"registration": a.registration, "operator": a.operator, "model": a.model, "last_seen": a.last_seen, "callsign": a.last_callsign, "lat": a.last_lat, "lon": a.last_lon} for a in recent],
        }


aviation_bot = AviationBot()
