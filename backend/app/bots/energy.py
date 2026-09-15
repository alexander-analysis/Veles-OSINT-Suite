"""Energy flow monitor (ecosystem bot 7) - where sanctioned oil, products and LNG actually move.

* ``sync_facilities`` - curated terminals / refineries / STS anchorages -> ``EnergyFacility`` rows (owners screened).
* ``track_facility_visits`` - tankers loitering inside a facility radius open / close a ``PortCallEvent``
  (with draught snapshots), also for facilities that are not in the generic port list.
* ``build_shipments`` - a laden departure from an export facility becomes an ``OilTankerShipment``;
  the tanker's next call closes it as the discharge leg (origin / destination countries, barrels).
* ``detect_dark_oil`` - sanctioned loadings, AIS gaps after loading, STS transfers, STS-hub loitering,
  spoofed positions and identity changes on tankers tied to sanctioned flows -> ``DarkOilIndicator``.
* ``snapshot_flows`` - daily per-facility aggregates and 7 / 30-day counters; ``price_context`` correlates
  laden departures from sanctioned facilities with Brent / WTI closes from the market bot.
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.energy import SANCTIONED_ORIGINS, estimate_cargo, facility_by_port, facility_containing, is_tanker, matches_commodity, pearson, score_pattern
from app.data.energy_facilities import FACILITIES
from app.database import SessionLocal
from app.models.audit import AuditLog
from app.models.energy import DarkOilIndicator, EnergyFacility, EnergyFlowSnapshot, OilTankerShipment
from app.models.maritime import EvasionEvent, PortCallEvent, TransshipmentEvent, Vessel
from app.models.market import MarketCandle
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="energy")

EXPORT_TYPES = ("crude_export", "product_export", "lng_export", "refinery")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("energy", {})


class EnergyBot:
    def __init__(self) -> None:
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}
        self._facility_ids: dict[str, int] = {}  # facility name -> id

    def status(self) -> dict[str, Any]:
        return {"last_run": dict(self.last_run), "last_result": self.last_result, "facilities": len(self._facility_ids)}

    # ------------------------------------------------------------- facilities
    async def sync_facilities(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._sync_facilities)
        self.last_run["facilities"] = utcnow()
        self.last_result["facilities"] = result
        log.info("facilities: {}", result)
        return result

    def _sync_facilities(self) -> dict[str, Any]:
        from app.bots.sanctions import sanctions_bot

        with SessionLocal() as db:
            existing = {f.facility_name: f for f in db.execute(select(EnergyFacility)).scalars()}
            added = 0
            for spec in FACILITIES:
                row = existing.get(spec["name"])
                if row is None:
                    row = EnergyFacility(facility_name=spec["name"], created_at=utcnow())
                    db.add(row)
                    added += 1
                row.facility_type = spec["type"]
                row.country = spec["country"]
                row.latitude, row.longitude, row.radius_km = spec["lat"], spec["lon"], spec["radius_km"]
                row.commodity = spec.get("commodity")
                row.production_capacity_bpd = spec.get("capacity_bpd")
                row.production_capacity_mtpa = spec.get("capacity_mtpa")
                row.operator_name = spec.get("operator")
                row.owner_name = spec.get("owner")
                row.is_sanctioned_facility = bool(spec.get("sanctioned"))
                row.sanctioning_authority = spec.get("authority")
                row.notes = spec.get("note")
                try:
                    row.owner_sanctioned = bool(spec.get("owner") and sanctions_bot.check_entity(spec["owner"].split("(")[0].strip(), "company", 0.9))
                except Exception:  # noqa: BLE001 - index not built yet
                    row.owner_sanctioned = row.owner_sanctioned or False
            db.commit()
            self._facility_ids = {f.facility_name: f.id for f in db.execute(select(EnergyFacility)).scalars()}
            return {"added": added, "total": len(self._facility_ids)}

    def _ensure_ids(self, db: Session) -> None:
        if not self._facility_ids:
            self._facility_ids = {f.facility_name: f.id for f in db.execute(select(EnergyFacility)).scalars()}

    # -------------------------------------------------------- facility visits
    async def track_facility_visits(self) -> dict[str, int]:
        result = await asyncio.to_thread(self._track_visits)
        self.last_run["visits"] = utcnow()
        self.last_result["visits"] = result
        return result

    def _track_visits(self) -> dict[str, int]:
        cfg = _config()
        max_speed = float(cfg.get("visit_max_speed_knots", 1.5))
        now = utcnow()
        opened = closed = linked = 0
        with SessionLocal() as db:
            self._ensure_ids(db)
            open_calls = {c.vessel_id: c for c in db.execute(select(PortCallEvent).where(PortCallEvent.departure_time.is_(None), PortCallEvent.energy_facility_id.is_not(None))).scalars()}
            # link generic port calls (maritime bot) to facilities by port name - tankers only, gas carriers for LNG plants
            unlinked = db.execute(
                select(PortCallEvent, Vessel.ship_type).join(Vessel, Vessel.id == PortCallEvent.vessel_id)
                .where(PortCallEvent.energy_facility_id.is_(None), PortCallEvent.arrival_time >= now - timedelta(days=45))
            ).all()
            for call, ship_type in unlinked:
                facility = facility_by_port(call.port_name)
                if facility and facility["name"] in self._facility_ids and matches_commodity(ship_type, facility.get("commodity")):
                    call.energy_facility_id = self._facility_ids[facility["name"]]
                    linked += 1
            # calls whose vessel has not reported for two days are closed as lost contact (the vessel left coverage)
            stale_cutoff = now - timedelta(hours=48)
            for call in list(open_calls.values()):
                vessel = db.get(Vessel, call.vessel_id)
                if vessel and vessel.last_ais_update and vessel.last_ais_update < stale_cutoff:
                    call.departure_time = vessel.last_ais_update
                    call.draught_departure = vessel.draught
                    call.dwell_time_hours = round((call.departure_time - call.arrival_time).total_seconds() / 3600, 2)
                    call.flags_raised = sorted(set(call.flags_raised or []) | {"lost_contact"})
                    open_calls.pop(call.vessel_id, None)
                    closed += 1
            recent = db.execute(select(Vessel).where(Vessel.last_ais_update >= now - timedelta(hours=3), Vessel.current_position_lat.is_not(None))).scalars().all()
            tankers = [v for v in recent if is_tanker(v.ship_type)]
            facility_call_names = {c.port_name for c in open_calls.values()}
            for vessel in tankers:
                found = facility_containing(vessel.current_position_lat, vessel.current_position_lon)
                if found and not matches_commodity(vessel.ship_type, found[0].get("commodity")):
                    found = None
                call = open_calls.get(vessel.id)
                if call is not None:
                    still_inside = found is not None and found[0]["name"] == call.port_name
                    if not still_inside or (vessel.current_speed or 0) >= 4.0:
                        call.departure_time = vessel.last_ais_update
                        call.draught_departure = vessel.draught
                        call.dwell_time_hours = round((call.departure_time - call.arrival_time).total_seconds() / 3600, 2)
                        closed += 1
                    continue
                if found is None or (vessel.current_speed or 0) > max_speed:
                    continue
                facility, _ = found
                if facility.get("port_name"):
                    continue  # the maritime bot already records calls for listed ports
                if facility["name"] in facility_call_names and any(c.vessel_id == vessel.id for c in open_calls.values()):
                    continue
                call = PortCallEvent(
                    vessel_id=vessel.id, mmsi=vessel.mmsi, port_name=facility["name"], port_code=None, port_country=facility["country"],
                    is_sanctioned_facility=bool(facility.get("sanctioned")), facility_risk_level="high" if facility.get("sanctioned") else "medium",
                    arrival_time=vessel.last_ais_update, cargo_type_predicted=facility.get("commodity"), flags_raised=["energy_facility"] + (["sanctioned_facility"] if facility.get("sanctioned") else []),
                    draught_arrival=vessel.draught, energy_facility_id=self._facility_ids.get(facility["name"]),
                )
                db.add(call)
                open_calls[vessel.id] = call
                opened += 1
                if facility.get("sanctioned"):
                    db.add(AuditLog(action_type="high_risk_port_call", user_id="system", vessel_id=vessel.id,
                                    rationale=f"{vessel.name} ({vessel.flag_state}) loitering at {facility['name']} ({facility['country']}) - {facility.get('note') or facility['type']}",
                                    supporting_data={"facility": facility["name"], "type": facility["type"]}, source_systems=["bots.energy"], created_by="system"))
            db.commit()
        return {"opened": opened, "closed": closed, "linked": linked}

    # ------------------------------------------------------------- shipments
    async def build_shipments(self) -> dict[str, int]:
        result = await asyncio.to_thread(self._build_shipments)
        self.last_run["shipments"] = utcnow()
        self.last_result["shipments"] = result
        if result.get("created") or result.get("discharged"):
            log.info("shipments: {}", result)
        return result

    def _build_shipments(self) -> dict[str, int]:
        now = utcnow()
        created = discharged = 0
        new_shipments: list[OilTankerShipment] = []
        with SessionLocal() as db:
            self._ensure_ids(db)
            facilities = {f.id: f for f in db.execute(select(EnergyFacility)).scalars()}
            known_calls = {s for (s,) in db.execute(select(OilTankerShipment.loading_port_call_id).where(OilTankerShipment.loading_port_call_id.is_not(None))).all()}
            departed = db.execute(
                select(PortCallEvent, Vessel).join(Vessel, Vessel.id == PortCallEvent.vessel_id)
                .where(PortCallEvent.energy_facility_id.is_not(None), PortCallEvent.departure_time.is_not(None), PortCallEvent.departure_time >= now - timedelta(days=60))
                .order_by(PortCallEvent.departure_time)
            ).all()
            for call, vessel in departed:
                if call.id in known_calls or not is_tanker(vessel.ship_type):
                    continue
                facility = facilities.get(call.energy_facility_id)
                if facility is None or facility.facility_type not in EXPORT_TYPES and facility.facility_type != "sts_hub":
                    continue
                estimate = estimate_cargo(vessel.length_m, call.draught_arrival, call.draught_departure, facility.commodity, loading=True)
                if estimate.laden is False and facility.facility_type != "sts_hub":
                    known_calls.add(call.id)
                    continue  # ballast departure - not a shipment
                sanctioned_route = bool(facility.is_sanctioned_facility or facility.country in SANCTIONED_ORIGINS)
                shipment = OilTankerShipment(
                    vessel_id=vessel.id, vessel_name=vessel.name, mmsi=vessel.mmsi, imo=vessel.imo, flag=vessel.flag_state,
                    cargo_type=facility.commodity or "unknown", cargo_volume_barrels=estimate.barrels, origin_country=facility.country,
                    loading_facility_id=facility.id, loading_location=facility.facility_name, loading_date=call.departure_time, loading_port_call_id=call.id,
                    draught_departure=call.draught_departure, draught_arrival=call.draught_arrival, laden=estimate.laden, sanctioned_route=sanctioned_route,
                    dark_oil_suspect=bool(sanctioned_route and ((vessel.sanctioned_status or "clear") != "clear" or (vessel.risk_score or 0) >= 0.5)),
                    status="underway", risk_score=round(0.3 + (0.4 if sanctioned_route else 0) + (0.3 if (vessel.sanctioned_status or "clear") != "clear" else 0), 2),
                    evidence={"size_class": estimate.size_class, "cargo_basis": estimate.basis, "dwell_hours": call.dwell_time_hours, "facility_type": facility.facility_type},
                    created_at=now, updated_at=now,
                )
                db.add(shipment)
                new_shipments.append(shipment)
                known_calls.add(call.id)
                created += 1
            # close open shipments with the next call of the same vessel (pending inserts are not flushed until commit,
            # so the write lock is only taken once at the end - the new rows are visited from memory)
            underway = list(db.execute(select(OilTankerShipment).where(OilTankerShipment.status == "underway")).scalars()) + new_shipments
            for shipment in underway:
                next_call = db.execute(
                    select(PortCallEvent).where(PortCallEvent.vessel_id == shipment.vessel_id, PortCallEvent.arrival_time > shipment.loading_date + timedelta(hours=6))
                    .order_by(PortCallEvent.arrival_time).limit(1)
                ).scalar_one_or_none()
                if next_call is None:
                    if shipment.loading_date < now - timedelta(days=75):
                        shipment.status = "stale"
                    continue
                dest = facilities.get(next_call.energy_facility_id) if next_call.energy_facility_id else None
                shipment.discharge_facility_id = dest.id if dest else None
                shipment.discharge_location = next_call.port_name
                shipment.discharge_date = next_call.arrival_time
                shipment.discharge_port_call_id = next_call.id
                shipment.destination_country = next_call.port_country
                if dest and dest.facility_type == "sts_hub":
                    shipment.transshipment_suspect = True
                shipment.status = "discharged" if not (dest and dest.facility_type == "sts_hub") else "transshipped"
                shipment.updated_at = now
                discharged += 1
            db.commit()
        return {"created": created, "discharged": discharged}

    # -------------------------------------------------------------- dark oil
    async def detect_dark_oil(self) -> dict[str, int]:
        result = await asyncio.to_thread(self._detect_dark_oil)
        self.last_run["dark_oil"] = utcnow()
        self.last_result["dark_oil"] = result
        if result.get("created"):
            log.info("dark oil: {}", result)
        return result

    def _detect_dark_oil(self) -> dict[str, int]:
        cfg = _config()
        now = utcnow()
        lookback = timedelta(days=int(cfg.get("dark_oil_lookback_days", 30)))
        loiter_hours = float(cfg.get("sts_loiter_hours", 24))
        created = 0
        with SessionLocal() as db:
            self._ensure_ids(db)
            facilities = {f.id: f for f in db.execute(select(EnergyFacility)).scalars()}
            existing = {(i.tanker_id, i.detected_pattern, i.shipment_id) for i in db.execute(select(DarkOilIndicator).where(DarkOilIndicator.detected_at >= now - lookback - timedelta(days=30))).scalars()}
            existing_recent = defaultdict(list)
            for i in db.execute(select(DarkOilIndicator).where(DarkOilIndicator.detected_at >= now - timedelta(days=7))).scalars():
                existing_recent[(i.tanker_id, i.detected_pattern)].append(i.detected_at)

            def add(tanker: Vessel, pattern: str, shipment: OilTankerShipment | None, evidence: dict, origin: str | None, destination: str | None, summary: str, extra: float = 0.0, voyage_start: datetime | None = None) -> None:
                nonlocal created
                key = (tanker.id, pattern, shipment.id if shipment else None)
                if key in existing:
                    return
                if shipment is None and existing_recent.get((tanker.id, pattern)):
                    return  # one per pattern per vessel per week when not tied to a shipment
                score, severity = score_pattern(pattern, (tanker.sanctioned_status or "clear") != "clear", tanker.risk_score, extra)
                db.add(DarkOilIndicator(tanker_id=tanker.id, tanker_name=tanker.name, mmsi=tanker.mmsi, detected_pattern=pattern, suspected_origin=origin, suspected_destination=destination,
                                        evidence=evidence, confidence_score=score, severity=severity, summary=summary[:300], shipment_id=shipment.id if shipment else None,
                                        detected_at=now, voyage_start=voyage_start))
                existing.add(key)
                existing_recent[(tanker.id, pattern)].append(now)
                created += 1
                if shipment is not None:
                    shipment.dark_oil_suspect = True
                    shipment.risk_score = round(min(1.0, (shipment.risk_score or 0.3) + 0.15), 2)
                if severity in ("high", "critical"):
                    from app import notifications

                    notifications.send_alert("energy", f"Dark oil indicator: {pattern.replace('_', ' ')}", summary, severity=severity, data={"vessel": tanker.name, "mmsi": tanker.mmsi})

            shipments = db.execute(select(OilTankerShipment, Vessel).join(Vessel, Vessel.id == OilTankerShipment.vessel_id).where(OilTankerShipment.loading_date >= now - lookback, OilTankerShipment.sanctioned_route.is_(True))).all()
            for shipment, vessel in shipments:
                facility = facilities.get(shipment.loading_facility_id)
                fname = facility.facility_name if facility else shipment.loading_location
                if (vessel.sanctioned_status or "clear") != "clear":
                    add(vessel, "sanctioned_vessel_loading", shipment, {"facility": fname, "status": vessel.sanctioned_status}, shipment.origin_country, shipment.destination_country,
                        f"{vessel.name} ({vessel.flag_state}) - {vessel.sanctioned_status} - loaded at {fname}", voyage_start=shipment.loading_date)
                else:
                    add(vessel, "sanctioned_loading", shipment, {"facility": fname, "barrels": shipment.cargo_volume_barrels, "laden": shipment.laden}, shipment.origin_country, shipment.destination_country,
                        f"{vessel.name} ({vessel.flag_state}) loaded {shipment.cargo_type} at {fname}" + (f" (~{int(shipment.cargo_volume_barrels):,} bbl)" if shipment.cargo_volume_barrels else ""), voyage_start=shipment.loading_date)
                window_end = shipment.discharge_date or now
                events = db.execute(select(EvasionEvent).where(EvasionEvent.vessel_id == vessel.id, EvasionEvent.timestamp >= shipment.loading_date, EvasionEvent.timestamp <= window_end + timedelta(days=2))).scalars().all()
                for event in events:
                    if event.event_type == "ais_gap":
                        add(vessel, "ais_gap_after_loading", shipment, {"gap": event.details, "event_id": event.id}, shipment.origin_country, shipment.destination_country,
                            f"{vessel.name} went dark for {(event.details or {}).get('gap_hours', '?')} h after loading at {fname}", voyage_start=shipment.loading_date)
                    elif event.event_type == "position_anomaly":
                        add(vessel, "spoofed_position", shipment, {"event_id": event.id, "details": event.details}, shipment.origin_country, shipment.destination_country,
                            f"{vessel.name}: implausible position report after loading at {fname}", voyage_start=shipment.loading_date)
                    elif event.event_type in ("name_change", "flag_change", "identity_conflict"):
                        add(vessel, "identity_change", shipment, {"event_id": event.id, "type": event.event_type, "details": event.details}, shipment.origin_country, shipment.destination_country,
                            f"{vessel.name}: {event.event_type.replace('_', ' ')} while carrying {fname} cargo", voyage_start=shipment.loading_date)
                sts = db.execute(select(TransshipmentEvent).where(or_(TransshipmentEvent.vessel_a_id == vessel.id, TransshipmentEvent.vessel_b_id == vessel.id),
                                                                  TransshipmentEvent.timestamp >= shipment.loading_date, TransshipmentEvent.timestamp <= window_end + timedelta(days=2))).scalars().all()
                for event in sts:
                    other_id = event.vessel_b_id if event.vessel_a_id == vessel.id else event.vessel_a_id
                    other = db.get(Vessel, other_id)
                    add(vessel, "sts_transfer", shipment, {"sts_event_id": event.id, "partner_mmsi": other.mmsi if other else None, "partner": other.name if other else None, "confidence": event.confidence_score},
                        shipment.origin_country, shipment.destination_country, f"{vessel.name} met {other.name if other else 'unknown vessel'} at sea after loading at {fname} (STS {event.confidence_score or 0:.2f})",
                        extra=0.1 if (event.confidence_score or 0) >= 0.7 else 0.0, voyage_start=shipment.loading_date)
                if shipment.destination_country in SANCTIONED_ORIGINS and shipment.destination_country != shipment.origin_country:
                    add(vessel, "discharge_to_sanctioned_destination", shipment, {"destination": shipment.discharge_location}, shipment.origin_country, shipment.destination_country,
                        f"{vessel.name} delivered {fname} cargo to {shipment.discharge_location} ({shipment.destination_country})", voyage_start=shipment.loading_date)
            # STS-hub loitering: open facility calls at sts hubs lasting longer than the threshold
            hub_ids = {fid for fid, f in facilities.items() if f.facility_type == "sts_hub"}
            if hub_ids:
                loiter_query = (
                    select(PortCallEvent, Vessel).join(Vessel, Vessel.id == PortCallEvent.vessel_id)
                    .where(PortCallEvent.energy_facility_id.in_(hub_ids), PortCallEvent.departure_time.is_(None), PortCallEvent.arrival_time <= now - timedelta(hours=loiter_hours))
                )
                loiter = db.execute(loiter_query).all()
                for call, vessel in loiter:
                    facility = facilities[call.energy_facility_id]
                    hours = round((now - call.arrival_time).total_seconds() / 3600)
                    add(vessel, "sts_hub_loitering", None, {"facility": facility.facility_name, "hours": hours, "call_id": call.id}, facility.country if facility.is_sanctioned_facility else None, None,
                        f"{vessel.name} ({vessel.flag_state}) has loitered {hours} h in the {facility.facility_name}", extra=0.1 if facility.is_sanctioned_facility else 0.0)
            db.commit()
        return {"created": created}

    # ------------------------------------------------------------- snapshots
    async def snapshot_flows(self) -> dict[str, int]:
        result = await asyncio.to_thread(self._snapshot_flows)
        self.last_run["snapshots"] = utcnow()
        self.last_result["snapshots"] = result
        return result

    def _snapshot_flows(self) -> dict[str, int]:
        now = utcnow()
        since = now - timedelta(days=int(_config().get("snapshot_days", 35)))
        updated = 0
        with SessionLocal() as db:
            self._ensure_ids(db)
            facilities = {f.id: f for f in db.execute(select(EnergyFacility)).scalars()}
            calls = db.execute(select(PortCallEvent, Vessel).join(Vessel, Vessel.id == PortCallEvent.vessel_id).where(PortCallEvent.energy_facility_id.is_not(None), or_(PortCallEvent.arrival_time >= since, PortCallEvent.departure_time >= since))).all()
            shipments = db.execute(select(OilTankerShipment).where(OilTankerShipment.loading_date >= since)).scalars().all()
            barrels: dict[tuple[int, datetime], float] = defaultdict(float)
            laden: dict[tuple[int, datetime], int] = defaultdict(int)
            for s in shipments:
                if s.loading_facility_id and s.loading_date:
                    day = s.loading_date.replace(hour=0, minute=0, second=0, microsecond=0)
                    laden[(s.loading_facility_id, day)] += 1 if s.laden else 0
                    barrels[(s.loading_facility_id, day)] += s.cargo_volume_barrels or 0
            arrivals: dict[tuple[int, datetime], int] = defaultdict(int)
            departures: dict[tuple[int, datetime], int] = defaultdict(int)
            flagged: dict[tuple[int, datetime], int] = defaultdict(int)
            counts_7d: dict[int, int] = defaultdict(int)
            counts_30d: dict[int, int] = defaultdict(int)
            last_activity: dict[int, datetime] = {}
            for call, vessel in calls:
                fid = call.energy_facility_id
                if not is_tanker(vessel.ship_type):
                    continue
                if call.arrival_time and call.arrival_time >= since:
                    day = call.arrival_time.replace(hour=0, minute=0, second=0, microsecond=0)
                    arrivals[(fid, day)] += 1
                    if (vessel.sanctioned_status or "clear") != "clear" or (vessel.risk_score or 0) >= 0.5:
                        flagged[(fid, day)] += 1
                    if call.arrival_time >= now - timedelta(days=7):
                        counts_7d[fid] += 1
                    if call.arrival_time >= now - timedelta(days=30):
                        counts_30d[fid] += 1
                    last_activity[fid] = max(last_activity.get(fid, call.arrival_time), call.arrival_time)
                if call.departure_time and call.departure_time >= since:
                    day = call.departure_time.replace(hour=0, minute=0, second=0, microsecond=0)
                    departures[(fid, day)] += 1
            keys = set(arrivals) | set(departures) | set(barrels)
            existing = {(s.facility_id, s.day): s for s in db.execute(select(EnergyFlowSnapshot).where(EnergyFlowSnapshot.day >= since)).scalars()}
            for key in keys:
                fid, day = key
                snap = existing.get(key)
                if snap is None:
                    snap = EnergyFlowSnapshot(facility_id=fid, day=day)
                    db.add(snap)
                snap.tanker_arrivals = arrivals.get(key, 0)
                snap.tanker_departures = departures.get(key, 0)
                snap.laden_departures = laden.get(key, 0)
                snap.estimated_barrels = barrels.get(key) or None
                snap.flagged_tankers = flagged.get(key, 0)
                updated += 1
            for fid, facility in facilities.items():
                facility.tanker_calls_7d = counts_7d.get(fid, 0)
                facility.tanker_calls_30d = counts_30d.get(fid, 0)
                if fid in last_activity:
                    facility.last_activity_at = last_activity[fid]
                month_barrels = sum(v for (f, _), v in barrels.items() if f == fid)
                facility.estimated_utilization = round(min(1.5, month_barrels / (facility.production_capacity_bpd * 30)), 3) if facility.production_capacity_bpd and month_barrels else None
            db.commit()
        return {"snapshots": updated}

    # ------------------------------------------------------ price context
    @staticmethod
    def price_context(db: Session, days: int = 30) -> dict[str, Any]:
        """Daily laden departures / barrels from sanctioned facilities against Brent (fallback WTI) closes."""
        since = utcnow() - timedelta(days=days)
        sanctioned_ids = [f.id for f in db.execute(select(EnergyFacility).where(EnergyFacility.is_sanctioned_facility.is_(True))).scalars()]
        flows: dict[str, dict[str, float]] = defaultdict(lambda: {"laden_departures": 0, "barrels": 0.0, "arrivals": 0, "flagged": 0})
        if sanctioned_ids:
            for snap in db.execute(select(EnergyFlowSnapshot).where(EnergyFlowSnapshot.facility_id.in_(sanctioned_ids), EnergyFlowSnapshot.day >= since)).scalars():
                key = snap.day.strftime("%Y-%m-%d")
                flows[key]["laden_departures"] += snap.laden_departures or 0
                flows[key]["barrels"] += snap.estimated_barrels or 0
                flows[key]["arrivals"] += snap.tanker_arrivals or 0
                flows[key]["flagged"] += snap.flagged_tankers or 0
        prices: dict[str, float] = {}
        asset_used = None
        for asset in ("BRENT", "OIL"):
            rows = db.execute(
                select(func.date(MarketCandle.timestamp), func.avg(MarketCandle.close)).where(MarketCandle.asset == asset, MarketCandle.timestamp >= since).group_by(func.date(MarketCandle.timestamp))
            ).all()
            if rows:
                prices = {str(d): round(float(p), 2) for d, p in rows if p is not None}
                asset_used = asset
                break
        days_sorted = sorted(set(flows) | set(prices))
        series = [{"day": d, **flows.get(d, {"laden_departures": 0, "barrels": 0.0, "arrivals": 0, "flagged": 0}), "price": prices.get(d)} for d in days_sorted]
        paired = [(s["laden_departures"], s["price"]) for s in series if s["price"] is not None]
        correlation = pearson([p[0] for p in paired], [p[1] for p in paired]) if len(paired) >= 5 else None
        return {"days": days, "price_asset": asset_used, "correlation_departures_price": correlation, "series": series}

    # ---------------------------------------------------------------- summary
    def summary(self, db: Session, days: int = 7) -> dict[str, Any]:
        since = utcnow() - timedelta(days=days)
        facilities = db.execute(select(EnergyFacility)).scalars().all()
        shipments = db.execute(select(func.count(OilTankerShipment.id)).where(OilTankerShipment.loading_date >= since)).scalar() or 0
        sanctioned = db.execute(select(func.count(OilTankerShipment.id)).where(OilTankerShipment.loading_date >= since, OilTankerShipment.sanctioned_route.is_(True))).scalar() or 0
        barrels = db.execute(select(func.sum(OilTankerShipment.cargo_volume_barrels)).where(OilTankerShipment.loading_date >= since, OilTankerShipment.sanctioned_route.is_(True))).scalar() or 0.0
        indicators = dict(db.execute(select(DarkOilIndicator.detected_pattern, func.count()).where(DarkOilIndicator.detected_at >= since).group_by(DarkOilIndicator.detected_pattern)).all())
        active = sorted((f for f in facilities if (f.tanker_calls_7d or 0) > 0), key=lambda f: -(f.tanker_calls_7d or 0))[:8]
        open_visits = db.execute(
            select(func.count(PortCallEvent.id)).join(Vessel, Vessel.id == PortCallEvent.vessel_id)
            .where(PortCallEvent.energy_facility_id.is_not(None), PortCallEvent.departure_time.is_(None), Vessel.last_ais_update >= utcnow() - timedelta(hours=6))
        ).scalar() or 0
        by_origin = dict(db.execute(select(OilTankerShipment.origin_country, func.count()).where(OilTankerShipment.loading_date >= since).group_by(OilTankerShipment.origin_country)).all())
        by_destination = dict(db.execute(select(OilTankerShipment.destination_country, func.count()).where(OilTankerShipment.loading_date >= since, OilTankerShipment.destination_country.is_not(None)).group_by(OilTankerShipment.destination_country)).all())
        return {
            "days": days,
            "facilities": len(facilities),
            "facilities_sanctioned": sum(1 for f in facilities if f.is_sanctioned_facility),
            "tankers_at_facilities_now": open_visits,
            "shipments": shipments,
            "sanctioned_shipments": sanctioned,
            "sanctioned_barrels": round(barrels),
            "dark_oil_indicators": indicators,
            "most_active": [{"facility": f.facility_name, "country": f.country, "type": f.facility_type, "calls_7d": f.tanker_calls_7d, "calls_30d": f.tanker_calls_30d, "sanctioned": f.is_sanctioned_facility} for f in active],
            "by_origin": by_origin,
            "by_destination": by_destination,
        }


energy_bot = EnergyBot()
