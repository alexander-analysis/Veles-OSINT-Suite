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

from sqlalchemy import delete, func, insert, or_, select
from sqlalchemy.orm import Session

from app.analysis import evasion, ports as port_rules, transshipment as sts
from app.analysis.geospatial import describe_location, lanes_containing, port_containing, zones_containing
from app.analysis.risk import compute_risk_score
from app import notifications
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
        self._last_history: dict[str, datetime] = {}  # mmsi -> timestamp of the last stored history fix

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
                elif kind == "nmea_tcp":
                    client = rtlsdr_receiver.NMEATCPClient(entry.get("host", "153.44.253.27"), int(entry.get("port", 5631)), entry.get("source", "nmea_tcp"))
                    await client.start()
                    self.sources[kind] = client
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
        history_interval = timedelta(minutes=float(cfg.get("history_interval_minutes", 60)))
        slow_interval = timedelta(minutes=float(cfg.get("history_slow_interval_minutes", 10)))
        risk_floor = float(cfg.get("history_risk_floor", 0.3))
        # newest report per MMSI wins
        latest: dict[str, AISPosition] = {}
        for position in positions:
            current = latest.get(position.mmsi)
            if current is None or position.timestamp > current.timestamp:
                latest[position.mmsi] = position
        # slow vessels with another slow vessel within ~1 km: the only ones whose track can time a rendezvous
        cell = 0.01
        slow_cells: dict[tuple[int, int], int] = defaultdict(int)
        for position in latest.values():
            if position.speed is not None and position.speed <= 2.0:
                slow_cells[(int(position.lat // cell), int(position.lon // cell))] += 1
        rendezvous_candidates = {
            position.mmsi
            for position in latest.values()
            if position.speed is not None and position.speed <= 2.0
            and sum(slow_cells.get((int(position.lat // cell) + dr, int(position.lon // cell) + dc), 0) for dr in (-1, 0, 1) for dc in (-1, 0, 1)) > 1
        }
        stats = defaultdict(int)
        updates: list[dict] = []
        # Short transactions: a global poll is thousands of vessels, and one long write
        # transaction would starve the other bots' writers on a Pi ("database is locked").
        chunk_size = int(cfg.get("ingest_chunk_size", 600))
        items = list(latest.items())
        for start in range(0, len(items), chunk_size):
            chunk = dict(items[start : start + chunk_size])
            self._ingest_chunk(chunk, cfg, rendezvous_candidates, gap_hours, history_interval, slow_interval, risk_floor, stats, updates)
        if updates:
            stream.publish("vessel_positions", {"count": len(updates), "vessels": updates[:2000]})
        return dict(stats)

    def _ingest_chunk(self, latest: dict[str, AISPosition], cfg: dict[str, Any], rendezvous_candidates: set[str], gap_hours: float,
                      history_interval: timedelta, slow_interval: timedelta, risk_floor: float, stats: dict, updates: list[dict]) -> None:
        lane_checks: list[tuple[Vessel, AISPosition]] = []
        breaches_found = 0
        with SessionLocal() as db:
            mmsis = list(latest)
            vessels: dict[str, Vessel] = {}
            for start in range(0, len(mmsis), 500):
                for vessel in db.execute(select(Vessel).where(Vessel.mmsi.in_(mmsis[start : start + 500]))).scalars():
                    vessels[vessel.mmsi] = vessel
            # every vessel currently holding an IMO claimed in this batch (uniqueness is enforced by the DB)
            imo_owner: dict[str, Vessel] = {}
            claimed_imos = list({p.imo for p in latest.values() if p.imo})
            for start in range(0, len(claimed_imos), 500):
                for vessel in db.execute(select(Vessel).where(Vessel.imo.in_(claimed_imos[start : start + 500]))).scalars():
                    imo_owner[vessel.imo] = vessel

            new_rows: list[tuple[Vessel, AISPosition]] = []
            reconcile: list[Vessel] = []
            new_vessels: list[Vessel] = []
            for mmsi, position in latest.items():
                vessel = vessels.get(mmsi)
                if vessel is None:
                    vessel = Vessel(mmsi=mmsi, name=position.name or f"MMSI {mmsi}", flag_state=position.flag or "XX", sanctioned_status="clear")
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
                    anomaly = evasion.detect_position_anomaly(vessel.last_ais_update, vessel.current_position_lat, vessel.current_position_lon, position, position.ship_type or vessel.ship_type)
                    if anomaly:
                        self._add_evasion(db, vessel, anomaly)
                        stats["position_anomalies"] += 1

                # static enrichment (never overwrite a known value with nothing)
                if position.imo and not vessel.imo and self._claim_imo(db, vessel, position, imo_owner, stats):
                    if vessel.id is not None and (vessel.sanctioned_status or "clear") != "clear":
                        reconcile.append(vessel)
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
                if self._keep_history(vessel, position, history_interval, risk_floor, slow_interval if mmsi in rendezvous_candidates else None):
                    new_rows.append((vessel, position))
                    self._last_history[mmsi] = position.timestamp
                else:
                    stats["history_skipped"] += 1
                lane_checks.append((vessel, position))
                if vessel.id:
                    self.touched.add(vessel.id)
                updates.append({"mmsi": mmsi, "name": vessel.name, "lat": position.lat, "lon": position.lon, "speed": position.speed, "heading": position.heading,
                                "flag": vessel.flag_state, "sanctioned_status": vessel.sanctioned_status, "timestamp": position.timestamp})
            db.flush()
            if new_rows:
                db.execute(
                    insert(VesselPosition),
                    [
                        {"vessel_id": v.id, "mmsi": v.mmsi, "timestamp": pos.timestamp, "latitude": pos.lat, "longitude": pos.lon, "heading": pos.heading,
                         "speed": pos.speed, "course": pos.course, "ais_source": pos.source, "signal_quality": pos.signal_quality, "created_at": utcnow()}
                        for v, pos in new_rows
                    ],
                )
            for vessel in reconcile:
                self._reconcile_breaches(db, vessel, stats)
            for vessel in new_vessels:
                self.touched.add(vessel.id)
                breaches_found += self._screen_vessel(db, vessel)
                first = latest[vessel.mmsi]
                anomaly = evasion.detect_position_anomaly(None, None, None, first, vessel.ship_type)
                if anomaly:
                    self._add_evasion(db, vessel, anomaly)
                    stats["position_anomalies"] += 1
            for vessel, position in lane_checks:
                self._lane_events(db, vessel, position, stats)
            db.commit()
            stats["positions"] += len(new_rows)
            stats["breaches"] += breaches_found

    def _claim_imo(self, db: Session, vessel: Vessel, position: AISPosition, imo_owner: dict[str, Vessel], stats: dict) -> bool:
        """Give ``vessel`` the reported IMO unless another MMSI holds it.

        A holder silent for more than a day has re-registered: the identity (and
        its history) transfers.  Two live transponders claiming one hull is
        spoofing: the newcomer gets an ``identity_conflict`` indicator and no IMO.
        """
        imo = position.imo
        holder = imo_owner.get(imo)
        if holder is None or holder is vessel:
            vessel.imo = imo
            imo_owner[imo] = vessel
            return True
        indicator = evasion.identity_conflict(holder, position)
        holder_silent = holder.last_ais_update is None or (position.timestamp - holder.last_ais_update) > timedelta(hours=24)
        if holder_silent:
            self._add_evasion(db, holder, indicator)
            vessel.historical_names = [*(vessel.historical_names or []), holder.name][-10:]
            vessel.historical_flags = [*(vessel.historical_flags or []), holder.flag_state][-10:]
            vessel.owner_name = vessel.owner_name or holder.owner_name
            vessel.registered_operator = vessel.registered_operator or holder.registered_operator
            vessel.beneficial_owner = vessel.beneficial_owner or holder.beneficial_owner
            holder.imo = None
            db.flush()  # release the unique value before re-assigning it
            vessel.imo = imo
            imo_owner[imo] = vessel
            stats["identity_transfers"] += 1
            return True
        self._add_evasion(db, vessel if vessel.id else holder, indicator)
        stats["identity_conflicts"] += 1
        return False

    def _keep_history(self, vessel: Vessel, position: AISPosition, interval: timedelta, risk_floor: float, slow_interval: timedelta | None = None) -> bool:
        """Store a history row for vessels of interest every fix; rendezvous candidates every ``slow_interval``; sample the rest."""
        if vessel.id is None or (vessel.sanctioned_status or "clear") != "clear" or (vessel.risk_score or 0) >= risk_floor:
            return True
        last = self._last_history.get(vessel.mmsi)
        if slow_interval is not None and port_containing(position.lat, position.lon) is None:
            return last is None or position.timestamp - last >= slow_interval
        if interval.total_seconds() <= 0:
            return False
        return last is None or position.timestamp - last >= interval

    def _reconcile_breaches(self, db: Session, vessel: Vessel, stats: dict) -> None:
        """A newly learned IMO settles name-only matches: clear those whose listed IMO differs."""
        index = sanctions_bot.index
        if index is None or not vessel.imo:
            return
        remaining: list[SanctionsBreach] = []
        for breach in list(vessel.breaches):
            if breach.investigation_status == "cleared":
                continue
            evidence = breach.supporting_evidence or {}
            entity = index.entities.get(breach.sanctioned_entity_id) if breach.sanctioned_entity_id else None
            if evidence.get("match_type") in ("name_exact", "name_fuzzy") and entity and entity.imo and entity.imo != vessel.imo:
                breach.investigation_status = "cleared"
                breach.analyst_notes = f"Auto-cleared: vessel IMO {vessel.imo} differs from listed IMO {entity.imo} (namesake)"
                db.add(AuditLog(action_type="cleared", user_id="system", vessel_id=vessel.id, breach_id=breach.id, sanctioned_entity_name=breach.sanctioned_entity_name,
                                sanctioning_authorities=[breach.sanctioning_authority], rationale=breach.analyst_notes, source_systems=["bots.maritime"], created_by="system"))
                stats["breaches_auto_cleared"] += 1
            else:
                remaining.append(breach)
        visible = [b for b in remaining if (b.match_confidence or 0) >= float(self.config().get("min_visible_confidence", 0.6))]
        if visible:
            vessel.sanctioned_status = f"breach_{max(visible, key=lambda b: b.match_confidence or 0).sanctioning_authority.lower()}"
        elif remaining:
            vessel.sanctioned_status = "flagged"
        else:
            vessel.sanctioned_status = "clear"
        # IMO now known: a direct identity match may exist
        self._screen_vessel(db, vessel)

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
                    stream.publish("breach_detected", {"vessel_name": vessel.name, "mmsi": vessel.mmsi, "breach_type": match.breach_type, "authority": match.authority, "severity": match.severity, "confidence": match.confidence, "location": {"lat": vessel.current_position_lat, "lon": vessel.current_position_lon}})
                    notifications.send_alert("breach", f"{match.authority} match: {vessel.name} ({vessel.flag_state})", match.summary, match.severity,
                                             {"mmsi": vessel.mmsi, "imo": vessel.imo, "confidence": match.confidence, "location": breach.location_description})
            if match.confidence >= visible_floor and (best_visible is None or match.confidence > best_visible[0]):
                best_visible = (match.confidence, match.authority)
        if best_visible:
            vessel.sanctioned_status = f"breach_{best_visible[1].lower()}"
        elif matches:
            vessel.sanctioned_status = "flagged" if (vessel.sanctioned_status or "clear") == "clear" else vessel.sanctioned_status
        return created

    async def check_sanctions(self, hours: int = 24) -> int:
        """Runs the synchronous body in a worker thread so the bot loop keeps serving streams."""
        return await asyncio.to_thread(self._check_sanctions_sync, hours)

    def _check_sanctions_sync(self, hours: int = 24) -> int:
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
        """Runs the synchronous body in a worker thread so the bot loop keeps serving streams."""
        return await asyncio.to_thread(self._detect_transshipments_sync)

    def _detect_transshipments_sync(self) -> int:
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
                notifications.send_alert("transshipment", f"Ship-to-ship candidate: {a.name} & {b.name}", candidate.summary, "high" if candidate.confidence >= 0.7 else "medium",
                                         {"vessel_a": a.mmsi, "vessel_b": b.mmsi, "confidence": candidate.confidence})
                stream.publish("transshipment_detected", {"vessel_a": {"mmsi": a.mmsi, "name": a.name}, "vessel_b": {"mmsi": b.mmsi, "name": b.name},
                                                          "proximity_meters": candidate.distance_m, "duration_minutes": candidate.duration_minutes,
                                                          "location": {"lat": candidate.lat, "lon": candidate.lon}, "confidence": candidate.confidence})
            db.commit()
        log.info("Transshipment scan: {} candidate pair(s), {} new event(s)", len(pairs), created)
        return created

    # ------------------------------------------------------------- port calls
    async def detect_port_calls(self) -> dict[str, int]:
        """Runs the synchronous body in a worker thread so the bot loop keeps serving streams."""
        return await asyncio.to_thread(self._detect_port_calls_sync)

    def _detect_port_calls_sync(self) -> dict[str, int]:
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
        """Runs the synchronous body in a worker thread so the bot loop keeps serving streams."""
        return await asyncio.to_thread(self._detect_dark_vessels_sync)

    def _detect_dark_vessels_sync(self) -> int:
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
        """Runs the synchronous body in a worker thread so the bot loop keeps serving streams."""
        return await asyncio.to_thread(self._update_risk_scores_sync, limit)

    def _update_risk_scores_sync(self, limit: int = 2000) -> int:
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
        """Runs the synchronous body in a worker thread so the bot loop keeps serving streams."""
        return await asyncio.to_thread(self._cleanup_old_data_sync)

    def _cleanup_old_data_sync(self) -> dict[str, int]:
        retention = config_store.get_config().get("retention", {})
        days = int(retention.get("vessel_positions_days", 180))
        compress_after = int(retention.get("vessel_positions_compress_after_days", 7))
        now = utcnow()
        with SessionLocal() as db:
            purged = db.execute(delete(VesselPosition).where(VesselPosition.timestamp < now - timedelta(days=days))).rowcount or 0
            # thin positions older than compress_after to one per N minutes per vessel
            thinned = 0
            thin_interval = timedelta(minutes=int(retention.get("vessel_positions_compress_interval_minutes", 30)))
            cutoff = now - timedelta(days=compress_after)
            rows = db.execute(select(VesselPosition.id, VesselPosition.vessel_id, VesselPosition.timestamp).where(VesselPosition.timestamp < cutoff).order_by(VesselPosition.vessel_id, VesselPosition.timestamp)).all()
            last_kept: dict[int, datetime] = {}
            to_delete = []
            for row_id, vessel_id, timestamp in rows:
                kept = last_kept.get(vessel_id)
                if kept and (timestamp - kept) < thin_interval:
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
