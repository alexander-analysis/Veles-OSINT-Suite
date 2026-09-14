"""Maritime intelligence bot.

Jobs (scheduled in ``app.bots.scheduler``, run on the bot event loop):

* ``fetch_ais_positions``   - poll every enabled AIS source, upsert vessels and
  positions, detect identity changes / AIS gaps / lane events at ingest,
  screen new vessels against the sanctions index, push WebSocket updates.
* ``check_sanctions``       - re-screen recently active vessels (also after
  each list refresh) and maintain ``SanctionsBreach`` rows.
* ``detect_transshipments`` - proximity clustering of loitering vessels.
* ``detect_port_calls``     - open/close ``PortCallEvent`` rows with flags.
* ``detect_dark_vessels``   - flagged vessels that stopped transmitting.
* ``update_risk_scores``    - composite risk for recently touched vessels.
* ``cleanup_old_data``      - position retention + thinning.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.analysis import evasion, ports as port_rules, transshipment as sts
from app.analysis.geospatial import describe_location, lanes_containing, zones_containing
from app.analysis.risk import compute_risk_score
from app.api.stream import manager as stream
from app.bots.sanctions import sanctions_bot
from app.config import settings
from app.data.ports import PORTS
from app.database import SessionLocal
from app.integrations import ais_hub, aisstream, digitraffic, marinetraffic, rtlsdr_receiver
from app.integrations.ais_common import AISPosition
from app.models.audit import AuditLog, DataRetentionPolicy
from app.models.maritime import (
    EvasionEvent,
    PortCallEvent,
    SanctionsBreach,
    ShippingLaneViolation,
    TransshipmentEvent,
    Vessel,
    VesselPosition,
)
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="maritime")


class MaritimeBot:
    def __init__(self) -> None:
        self.sources: dict[str, Any] = {}
        self.source_errors: dict[str, str] = {}
        self.last_fetch_at: datetime | None = None
        self.last_fetch_counts: dict[str, int] = {}
        self.last_ingest: dict[str, int] = {}
        self.last_sanctions_check_at: datetime | None = None
        self.last_index_seen: datetime | None = None
        self.touched: set[int] = set()  # vessel ids changed since the last risk-score pass

    # ------------------------------------------------------------------ config
    @staticmethod
    def config() -> dict[str, Any]:
        return config_store.get_config().get("maritime", {})

    async def ensure_sources(self) -> None:
        """Instantiate enabled sources once; key-gated sources stay off without credentials."""
        for entry in self.config().get("ais_sources", []):
            kind = entry.get("type")
            if not entry.get("enabled", False) or kind in self.sources:
                continue
            try:
                if kind == "digitraffic":
                    self.sources[kind] = digitraffic.DigitrafficClient()
                elif kind == "aisstream":
                    key = settings.key("AISSTREAM_API_KEY")
                    if not key:
                        self.source_errors[kind] = "AISSTREAM_API_KEY not set"
                        continue
                    client = aisstream.AISStreamClient(key, entry.get("bounding_boxes"))
                    client.start()
                    self.sources[kind] = client
                elif kind == "marinetraffic":
                    key = settings.key("MARINETRAFFIC_API_KEY")
                    if not key:
                        self.source_errors[kind] = "MARINETRAFFIC_API_KEY not set"
                        continue
                    bbox = entry.get("bbox")
                    self.sources[kind] = marinetraffic.MarineTrafficClient(key, tuple(bbox) if bbox else None)
                elif kind == "ais_hub":
                    user = settings.key("AISHUB_USERNAME")
                    if not user:
                        self.source_errors[kind] = "AISHUB_USERNAME not set"
                        continue
                    bbox = entry.get("bbox")
                    self.sources[kind] = ais_hub.AISHubClient(user, tuple(bbox) if bbox else None)
                elif kind == "rtl_sdr":
                    receiver = rtlsdr_receiver.NMEAUDPReceiver(port=int(entry.get("udp_port", settings.RTL_AIS_UDP_PORT)))
                    await receiver.start()
                    self.sources[kind] = receiver
            except Exception as exc:  # noqa: BLE001
                self.source_errors[kind] = str(exc)
                log.error("{} source init failed: {}", kind, exc)

    async def close(self) -> None:
        for name, source in self.sources.items():
            try:
                if hasattr(source, "stop"):
                    result = source.stop()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception:  # noqa: BLE001
                pass
        self.sources.clear()

    # -------------------------------------------------------------- ingestion
    async def fetch_ais_positions(self) -> dict[str, int]:
        await self.ensure_sources()
        cfg = self.config()
        max_age = int(cfg.get("max_position_age_minutes", 30))
        counts: dict[str, int] = {}
        positions: list[AISPosition] = []
        for name, source in self.sources.items():
            try:
                if hasattr(source, "drain"):
                    batch = source.drain()
                elif name == "digitraffic":
                    batch = await source.fetch_positions(max_age_minutes=max_age)
                else:
                    batch = await source.fetch_positions()
                counts[name] = len(batch)
                positions.extend(batch)
                self.source_errors.pop(name, None)
            except Exception as exc:  # noqa: BLE001
                self.source_errors[name] = str(exc)
                log.error("{}: fetch failed - {}", name, exc)
        if positions:
            self.last_ingest = await asyncio.to_thread(self._ingest, positions, cfg)
        self.last_fetch_at = utcnow()
        self.last_fetch_counts = counts
        log.info("AIS poll: {} positions from {} source(s) - {}", len(positions), len(counts), self.last_ingest)
        return counts

    def _ingest(self, positions: list[AISPosition], cfg: dict[str, Any]) -> dict[str, int]:
        """Upsert vessels/positions and run the per-report detectors."""
        gap_hours = float(cfg.get("ais_gap_threshold_hours", 6))
        # newest report per MMSI wins
        latest: dict[str, AISPosition] = {}
        for position in positions:
            current = latest.get(position.mmsi)
            if current is None or position.timestamp > current.timestamp:
                latest[position.mmsi] = position
        stats = defaultdict(int)
        updates: list[dict] = []
        lane_checks: list[tuple[Vessel, AISPosition]] = []
        breaches_found = 0
        with SessionLocal() as db:
            mmsis = list(latest)
            vessels: dict[str, Vessel] = {}
            for start in range(0, len(mmsis), 500):
                for vessel in db.execute(select(Vessel).where(Vessel.mmsi.in_(mmsis[start : start + 500]))).scalars():
                    vessels[vessel.mmsi] = vessel
            imo_map: dict[str, Vessel] = {}
            wanted_imos = [p.imo for p in latest.values() if p.imo and p.mmsi not in vessels]
            for start in range(0, len(wanted_imos), 500):
                for vessel in db.execute(select(Vessel).where(Vessel.imo.in_(wanted_imos[start : start + 500]))).scalars():
                    imo_map[vessel.imo] = vessel

            new_rows: list[VesselPosition] = []
            new_vessels: list[Vessel] = []
            for mmsi, position in latest.items():
                vessel = vessels.get(mmsi)
                if vessel is None:
                    vessel = Vessel(mmsi=mmsi, name=position.name or f"MMSI {mmsi}", flag_state=position.flag or "XX", sanctioned_status="clear")
                    conflict = imo_map.get(position.imo) if position.imo else None
                    if conflict is not None:
                        indicator = evasion.identity_conflict(conflict, position)
                        self._add_evasion(db, conflict, indicator)
                        vessel.historical_names = [conflict.name]
                        vessel.historical_flags = [conflict.flag_state]
                        vessel.owner_name, vessel.registered_operator, vessel.beneficial_owner = conflict.owner_name, conflict.registered_operator, conflict.beneficial_owner
                        conflict.imo = None  # the hull now reports under the new MMSI; keep uniqueness intact
                        stats["identity_conflicts"] += 1
                    db.add(vessel)
                    new_vessels.append(vessel)
                    vessels[mmsi] = vessel
                    stats["new_vessels"] += 1
                else:
                    if vessel.last_ais_update and position.timestamp <= vessel.last_ais_update:
                        stats["stale"] += 1
                        continue
                    for indicator in evasion.detect_identity_changes(vessel, position):
                        self._add_evasion(db, vessel, indicator)
                        stats[indicator.event_type] += 1
                    if position.name and position.name.upper() != (vessel.name or "").upper():
                        if not vessel.name.startswith("MMSI "):
                            vessel.historical_names = [*(vessel.historical_names or []), vessel.name][-10:]
                        vessel.name = position.name
                    if position.flag and position.flag != "XX" and position.flag != vessel.flag_state:
                        vessel.historical_flags = [*(vessel.historical_flags or []), vessel.flag_state][-10:]
                        vessel.flag_state = position.flag
                    gap = evasion.detect_ais_gap(vessel.last_ais_update, vessel.current_speed, vessel.current_position_lat, vessel.current_position_lon, position, gap_hours)
                    if gap:
                        self._add_evasion(db, vessel, gap)
                        stats["ais_gaps"] += 1

                # static enrichment (never overwrite a known value with nothing)
                if position.imo and not vessel.imo and position.imo not in imo_map:
                    vessel.imo = position.imo
                if position.call_sign and not vessel.call_sign:
                    vessel.call_sign = position.call_sign
                if position.ship_type and (not vessel.ship_type or vessel.ship_type == "Other"):
                    vessel.ship_type = position.ship_type
                if position.destination:
                    vessel.destination = position.destination[:100]
                vessel.current_position_lat, vessel.current_position_lon = position.lat, position.lon
                vessel.current_heading, vessel.current_speed = position.heading, position.speed
                vessel.ais_status = position.nav_status
                vessel.last_ais_update = position.timestamp
                vessel.ais_source = position.source
                new_rows.append(
                    VesselPosition(
                        vessel=vessel, mmsi=mmsi, timestamp=position.timestamp, latitude=position.lat, longitude=position.lon,
                        heading=position.heading, speed=position.speed, course=position.course, ais_source=position.source, signal_quality=position.signal_quality,
                    )
                )
                lane_checks.append((vessel, position))
                if vessel.id:
                    self.touched.add(vessel.id)
                updates.append({"mmsi": mmsi, "name": vessel.name, "lat": position.lat, "lon": position.lon, "speed": position.speed, "heading": position.heading,
                                "flag": vessel.flag_state, "sanctioned_status": vessel.sanctioned_status, "timestamp": position.timestamp})
            db.add_all(new_rows)
            db.flush()
            for vessel in new_vessels:
                self.touched.add(vessel.id)
                breaches_found += self._screen_vessel(db, vessel)
            for vessel, position in lane_checks:
                self._lane_events(db, vessel, position, stats)
            db.commit()
            stats["positions"] = len(new_rows)
            stats["breaches"] = breaches_found
        if updates:
            stream.publish("vessel_positions", {"count": len(updates), "vessels": updates[:2000]})
        return dict(stats)

    def _lane_events(self, db: Session, vessel: Vessel, position: AISPosition, stats: dict) -> None:
        """Record chokepoint transits of risky vessels and any entry into sanctions/war zones."""
        risky = (vessel.sanctioned_status or "clear") != "clear" or (vessel.risk_score or 0) >= 0.5
        areas = [(lane, "choke_point") for lane in lanes_containing(position.lat, position.lon) if lane.choke_point and risky]
        areas += [(zone, zone.kind) for zone in zones_containing(position.lat, position.lon) if zone.kind in ("sanctions_zone", "war_zone")]
        if not areas or vessel.id is None:
            return
        day_start = position.timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        for area, context in areas:
            exists = db.execute(
                select(ShippingLaneViolation.id).where(ShippingLaneViolation.vessel_id == vessel.id, ShippingLaneViolation.lane_name == area.name, ShippingLaneViolation.timestamp >= day_start)
            ).first()
            if exists:
                continue
            severity = "high" if (context == "sanctions_zone" and risky) else "medium" if risky or context == "sanctions_zone" else "low"
            db.add(
                ShippingLaneViolation(
                    vessel_id=vessel.id, mmsi=vessel.mmsi, lane_name=area.name, deviation_distance_nm=0.0, timestamp=position.timestamp, severity=severity, context=context,
                    reason_suspected=f"{vessel.name} ({vessel.flag_state}, {vessel.sanctioned_status}) inside {area.name}" + (f": {area.context}" if area.context else ""),
                )
            )
            stats["lane_events"] += 1

    def _add_evasion(self, db: Session, vessel: Vessel, indicator: evasion.EvasionIndicator) -> None:
        if vessel.id is not None:
            duplicate = db.execute(
                select(EvasionEvent.id).where(EvasionEvent.vessel_id == vessel.id, EvasionEvent.event_type == indicator.event_type, EvasionEvent.timestamp == indicator.timestamp)
            ).first()
            if duplicate:
                return
        db.add(
            EvasionEvent(
                vessel=vessel, mmsi=vessel.mmsi, event_type=indicator.event_type, severity=indicator.severity, confidence_score=indicator.confidence,
                timestamp=indicator.timestamp, location_lat=indicator.lat, location_lon=indicator.lon, details=indicator.details, summary=indicator.summary[:300],
            )
        )
        if vessel.id:
            self.touched.add(vessel.id)
        log.warning("evasion [{}] {}: {}", indicator.severity, vessel.mmsi, indicator.summary)

    # -------------------------------------------------------------- sanctions
    def _screen_vessel(self, db: Session, vessel: Vessel) -> int:
        """Match one vessel against the index; create/update breach rows. Returns new breaches."""
        cfg = self.config()
        review_floor = float(cfg.get("review_queue_min_confidence", 0.4))
        visible_floor = float(cfg.get("min_visible_confidence", 0.6))
        if sanctions_bot.index is None:
            return 0
        matches = sanctions_bot.check_vessel(vessel, min_confidence=review_floor)
        created = 0
        best_visible: tuple[float, str] | None = None
        for match in matches:
            entity_name = match.entity.name if match.entity else f"Comprehensive programme: {', '.join(match.programs)}"
            existing = db.execute(
                select(SanctionsBreach).where(
                    SanctionsBreach.vessel_id == vessel.id, SanctionsBreach.sanctioning_authority == match.authority,
                    SanctionsBreach.sanctioned_entity_name == entity_name, SanctionsBreach.breach_type == match.breach_type,
                )
            ).scalar_one_or_none()
            if existing:
                existing.match_confidence = max(existing.match_confidence or 0, match.confidence)
                existing.last_confirmed_at = utcnow()
                existing.location_lat, existing.location_lon = vessel.current_position_lat, vessel.current_position_lon
            else:
                breach = SanctionsBreach(
                    vessel=vessel, vessel_name=vessel.name, mmsi=vessel.mmsi, imo=vessel.imo, flag=vessel.flag_state, breach_type=match.breach_type,
                    sanctioning_authority=match.authority, sanctioned_entity_name=entity_name, sanctioned_entity_id=match.entity.id if match.entity else None,
                    match_confidence=match.confidence, severity=match.severity, location_lat=vessel.current_position_lat, location_lon=vessel.current_position_lon,
                    location_description=describe_location(vessel.current_position_lat, vessel.current_position_lon) if vessel.current_position_lat is not None else None,
                    timestamp=utcnow(), investigation_status="flagged" if match.confidence >= visible_floor else "review",
                    supporting_evidence={"match_type": match.match_type, "matched_value": match.matched_value, "similarity": match.similarity, "programs": match.programs, "summary": match.summary},
                )
                db.add(breach)
                db.flush()
                db.add(
                    AuditLog(
                        action_type="breach_detected", user_id="system", vessel_id=vessel.id, breach_id=breach.id, sanctioned_entity_name=entity_name,
                        sanctioning_authorities=[match.authority], rationale=match.summary,
                        supporting_data={"mmsi": vessel.mmsi, "imo": vessel.imo, "confidence": match.confidence, "breach_type": match.breach_type, "lat": vessel.current_position_lat, "lon": vessel.current_position_lon},
                        source_systems=["bots.maritime", "bots.sanctions"], created_by="system",
                    )
                )
                created += 1
                if match.confidence >= visible_floor:
                    log.warning("BREACH {} {} ({}) - {} {:.2f}: {}", match.authority, vessel.name, vessel.mmsi, match.breach_type, match.confidence, match.summary)
                    stream.publish("breach_detected", {"vessel_name": vessel.name, "mmsi": vessel.mmsi, "breach_type": match.breach_type, "authority": match.authority,
                                                        "severity": match.severity, "confidence": match.confidence, "location": {"lat": vessel.current_position_lat, "lon": vessel.current_position_lon}})
            if match.confidence >= visible_floor and (best_visible is None or match.confidence > best_visible[0]):
                best_visible = (match.confidence, match.authority)
        if best_visible:
            vessel.sanctioned_status = f"breach_{best_visible[1].lower()}"
        elif matches:
            vessel.sanctioned_status = "flagged" if (vessel.sanctioned_status or "clear") == "clear" else vessel.sanctioned_status
        return created

    async def check_sanctions(self, hours: int = 24) -> int:
        """Re-screen vessels active in the last ``hours`` (all vessels after a list refresh)."""
        index = sanctions_bot.index
        if index is None:
            log.info("sanctions index not ready - skipping vessel screening")
            return 0
        full = self.last_index_seen is None or index.built_at > self.last_index_seen
        with SessionLocal() as db:
            stmt = select(Vessel) if full else select(Vessel).where(Vessel.last_ais_update >= utcnow() - timedelta(hours=hours))
            vessels = db.execute(stmt).scalars().all()
            created = sum(self._screen_vessel(db, vessel) for vessel in vessels)
            db.commit()
        self.last_index_seen = index.built_at
        self.last_sanctions_check_at = utcnow()
        log.info("Sanctions screening: {} vessel(s) checked ({}), {} new breach(es)", len(vessels), "full" if full else f"last {hours}h", created)
        return created

    # ----------------------------------------------------------- transshipment
    async def detect_transshipments(self) -> int:
        cfg = self.config()
        proximity = float(cfg.get("transshipment_proximity_meters", 500))
        min_duration = int(cfg.get("transshipment_min_duration_minutes", 30))
        now = utcnow()
        created = 0
        with SessionLocal() as db:
            recent = db.execute(select(Vessel).where(Vessel.last_ais_update >= now - timedelta(minutes=30), Vessel.current_position_lat.isnot(None))).scalars().all()
            pairs = sts.find_proximity_pairs(recent, proximity, float(cfg.get("transshipment_max_speed_knots", 1.5)))
            window = timedelta(hours=8)
            for a, b, distance in pairs:
                history_a = db.execute(select(VesselPosition).where(VesselPosition.vessel_id == a.id, VesselPosition.timestamp >= now - window)).scalars().all()
                history_b = db.execute(select(VesselPosition).where(VesselPosition.vessel_id == b.id, VesselPosition.timestamp >= now - window)).scalars().all()
                duration, started = sts.proximity_duration(history_a, history_b, proximity, window)
                candidate = sts.assess_candidate(a, b, distance, duration, started, min_duration, now)
                if candidate is None:
                    continue
                existing = db.execute(
                    select(TransshipmentEvent).where(
                        or_((TransshipmentEvent.vessel_a_id == a.id) & (TransshipmentEvent.vessel_b_id == b.id), (TransshipmentEvent.vessel_a_id == b.id) & (TransshipmentEvent.vessel_b_id == a.id)),
                        TransshipmentEvent.timestamp >= candidate.started_at - timedelta(hours=2),
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.duration_minutes = max(existing.duration_minutes or 0, candidate.duration_minutes)
                    existing.confidence_score = max(existing.confidence_score or 0, candidate.confidence)
                    existing.proximity_meters = min(existing.proximity_meters or distance, distance)
                    existing.supporting_evidence = candidate.evidence
                    continue
                event = TransshipmentEvent(
                    vessel_a_id=a.id, vessel_b_id=b.id, vessel_a_mmsi=a.mmsi, vessel_b_mmsi=b.mmsi, timestamp=candidate.started_at, location_lat=candidate.lat, location_lon=candidate.lon,
                    proximity_meters=candidate.distance_m, duration_minutes=candidate.duration_minutes, confidence_score=candidate.confidence, investigation_status="possible",
                    supporting_evidence=candidate.evidence, analyst_notes=None,
                )
                db.add(event)
                db.add(AuditLog(action_type="transshipment_detected", user_id="system", vessel_id=a.id, rationale=candidate.summary,
                                supporting_data={"vessel_a": a.mmsi, "vessel_b": b.mmsi, **candidate.evidence}, related_entities=[{"mmsi": b.mmsi, "name": b.name}],
                                source_systems=["bots.maritime"], created_by="system"))
                self.touched.update({a.id, b.id})
                created += 1
                log.warning("STS candidate ({:.2f}): {}", candidate.confidence, candidate.summary)
                stream.publish("transshipment_detected", {"vessel_a": {"mmsi": a.mmsi, "name": a.name}, "vessel_b": {"mmsi": b.mmsi, "name": b.name},
                                                          "proximity_meters": candidate.distance_m, "duration_minutes": candidate.duration_minutes,
                                                          "location": {"lat": candidate.lat, "lon": candidate.lon}, "confidence": candidate.confidence})
            db.commit()
        log.info("Transshipment scan: {} candidate pair(s), {} new event(s)", len(pairs), created)
        return created

    # ------------------------------------------------------------- port calls
    async def detect_port_calls(self) -> dict[str, int]:
        cfg = self.config()
        unusual = float(cfg.get("unusual_dwell_time_hours", 72))
        now = utcnow()
        opened = closed = 0
        with SessionLocal() as db:
            open_calls = {c.vessel_id: c for c in db.execute(select(PortCallEvent).where(PortCallEvent.departure_time.is_(None))).scalars()}
            vessels = db.execute(select(Vessel).where(Vessel.last_ais_update >= now - timedelta(hours=2), Vessel.current_position_lat.isnot(None))).scalars().all()
            for vessel in vessels:
                state = port_rules.port_for_vessel(vessel)
                call = open_calls.get(vessel.id)
                if call is not None:
                    if port_rules.is_departure(vessel, call, state):
                        call.departure_time = vessel.last_ais_update
                        call.dwell_time_hours = port_rules.dwell_hours(call.arrival_time, call.departure_time)
                        port = next((p for p in PORTS if p["name"] == call.port_name), {})
                        call.flags_raised = port_rules.port_flags(port, call.dwell_time_hours, unusual, vessel)
                        vessel.last_port_name, vessel.last_port_time = call.port_name, call.departure_time
                        closed += 1
                        self.touched.add(vessel.id)
                    elif (now - call.arrival_time).total_seconds() / 3600 >= unusual and "unusual_dwell_time" not in (call.flags_raised or []):
                        call.flags_raised = sorted(set(call.flags_raised or []) | {"unusual_dwell_time"})
                    continue
                if port_rules.is_arrival(vessel, state):
                    port = state.port
                    call = PortCallEvent(
                        vessel_id=vessel.id, mmsi=vessel.mmsi, port_name=port["name"], port_code=port.get("unlocode"), port_country=port.get("country"),
                        is_sanctioned_facility=bool(port.get("sanctioned_facility")), facility_risk_level=port.get("risk_level"), arrival_time=vessel.last_ais_update,
                        cargo_type_predicted=port_rules.predicted_cargo(vessel, port), flags_raised=port_rules.port_flags(port, None, unusual, vessel),
                    )
                    db.add(call)
                    open_calls[vessel.id] = call
                    opened += 1
                    self.touched.add(vessel.id)
                    if port.get("sanctioned_facility") or port.get("risk_level") == "high":
                        db.add(AuditLog(action_type="high_risk_port_call", user_id="system", vessel_id=vessel.id,
                                        rationale=f"{vessel.name} ({vessel.flag_state}) arrived at {port['name']} ({port['country']}) - {port.get('note') or port.get('risk_level')}",
                                        supporting_data={"port": port["name"], "flags": call.flags_raised}, source_systems=["bots.maritime"], created_by="system"))
                        log.warning("high-risk port call: {} ({}) at {}", vessel.name, vessel.mmsi, port["name"])
            db.commit()
        log.info("Port calls: {} opened, {} closed", opened, closed)
        return {"opened": opened, "closed": closed}

    # ------------------------------------------------------------ dark vessels
    async def detect_dark_vessels(self) -> int:
        threshold = float(self.config().get("ais_gap_threshold_hours", 6))
        now = utcnow()
        created = 0
        with SessionLocal() as db:
            candidates = db.execute(
                select(Vessel).where(Vessel.last_ais_update < now - timedelta(hours=threshold), Vessel.last_ais_update >= now - timedelta(days=7),
                                     or_(Vessel.sanctioned_status != "clear", Vessel.risk_score >= 0.5))
            ).scalars().all()
            for vessel in candidates:
                indicator = evasion.dark_vessel_indicator(vessel, now, threshold)
                if indicator is None:
                    continue
                before = db.execute(select(func.count(EvasionEvent.id)).where(EvasionEvent.vessel_id == vessel.id, EvasionEvent.timestamp == indicator.timestamp, EvasionEvent.event_type == indicator.event_type)).scalar()
                if before:
                    continue
                self._add_evasion(db, vessel, indicator)
                created += 1
            db.commit()
        return created

    # -------------------------------------------------------------- risk score
    async def update_risk_scores(self, limit: int = 2000) -> int:
        ids = list(self.touched)[:limit]
        self.touched.difference_update(ids)
        if not ids:
            return 0
        with SessionLocal() as db:
            vessels = db.execute(select(Vessel).where(Vessel.id.in_(ids))).scalars().all()
            for vessel in vessels:
                score, _factors = compute_risk_score(db, vessel)
                vessel.risk_score = score
            db.commit()
        return len(vessels)

    # ----------------------------------------------------------------- cleanup
    async def cleanup_old_data(self) -> dict[str, int]:
        retention = config_store.get_config().get("retention", {})
        days = int(retention.get("vessel_positions_days", 180))
        compress_after = int(retention.get("vessel_positions_compress_after_days", 7))
        now = utcnow()
        with SessionLocal() as db:
            purged = db.execute(delete(VesselPosition).where(VesselPosition.timestamp < now - timedelta(days=days))).rowcount or 0
            # thin positions older than compress_after to one per 10 minutes per vessel
            thinned = 0
            cutoff = now - timedelta(days=compress_after)
            rows = db.execute(select(VesselPosition.id, VesselPosition.vessel_id, VesselPosition.timestamp).where(VesselPosition.timestamp < cutoff).order_by(VesselPosition.vessel_id, VesselPosition.timestamp)).all()
            last_kept: dict[int, datetime] = {}
            to_delete = []
            for row_id, vessel_id, timestamp in rows:
                kept = last_kept.get(vessel_id)
                if kept and (timestamp - kept) < timedelta(minutes=10):
                    to_delete.append(row_id)
                else:
                    last_kept[vessel_id] = timestamp
            for start in range(0, len(to_delete), 900):
                thinned += db.execute(delete(VesselPosition).where(VesselPosition.id.in_(to_delete[start : start + 900]))).rowcount or 0
            policy = db.execute(select(DataRetentionPolicy).where(DataRetentionPolicy.data_type == "vessel_positions")).scalar_one_or_none() or DataRetentionPolicy(data_type="vessel_positions", retention_days=days)
            policy.retention_days, policy.compression_after_days, policy.last_purge_at, policy.records_purged = days, compress_after, now, purged + thinned
            db.add(policy)
            db.commit()
        log.info("Position retention: purged {} (> {} d), thinned {} (> {} d)", purged, days, thinned, compress_after)
        return {"purged": purged, "thinned": thinned}

    # ------------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        with SessionLocal() as db:
            vessels = db.execute(select(func.count(Vessel.id))).scalar() or 0
            active = db.execute(select(func.count(Vessel.id)).where(Vessel.last_ais_update >= utcnow() - timedelta(hours=1))).scalar() or 0
            breaches = db.execute(select(func.count(SanctionsBreach.id)).where(SanctionsBreach.investigation_status.in_(["flagged", "investigating", "escalated"]))).scalar() or 0
            positions = db.execute(select(func.count(VesselPosition.id))).scalar() or 0
        return {
            "sources": {name: type(source).__name__ for name, source in self.sources.items()},
            "source_errors": self.source_errors,
            "last_fetch_at": self.last_fetch_at,
            "last_fetch_counts": self.last_fetch_counts,
            "last_ingest": self.last_ingest,
            "last_sanctions_check_at": self.last_sanctions_check_at,
            "vessels_tracked": vessels,
            "vessels_active_1h": active,
            "positions_stored": positions,
            "open_breaches": breaches,
            "stream": stream.status(),
        }


maritime_bot = MaritimeBot()
