"""Global search: one query across every domain VELES holds - vessels, listings, companies, wallets, aircraft, domains, events."""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.blockchain import BlockchainWallet
from app.models.corporate import Company
from app.models.geopolitical import GeopoliticalEvent
from app.models.maritime import Vessel
from app.models.sanctions import SanctionsEntity
from app.models.tier2 import Aircraft, InfraAsset, LegalEvent, Narrative, PscEvent
from app.utils.serialization import jsonable

router = APIRouter(tags=["search"])


def _hit(kind: str, id_: int, title: str, subtitle: str, href: str, **extra: Any) -> dict[str, Any]:
    return {"kind": kind, "id": id_, "title": title, "subtitle": subtitle, "href": href, **extra}


@router.get("")
def global_search(q: str = Query(..., min_length=2, max_length=120), per_kind: int = Query(8, ge=1, le=50), db: Session = Depends(get_db)) -> dict[str, Any]:
    """Case-insensitive substring search per domain; an all-digit query is also tried as an exact MMSI / IMO / LEI."""
    q = q.strip()
    like = f"%{q}%"
    digits = q.isdigit()
    groups: dict[str, list[dict[str, Any]]] = {}

    if digits:
        vessel_filter = or_(Vessel.mmsi == q, Vessel.imo == q, Vessel.mmsi.like(like), Vessel.imo.like(like))
    else:
        vessel_filter = or_(Vessel.name.ilike(like), Vessel.call_sign.ilike(q), Vessel.owner_name.ilike(like), Vessel.registered_operator.ilike(like), Vessel.beneficial_owner.ilike(like))
    vessels = db.execute(select(Vessel).where(vessel_filter).order_by(Vessel.risk_score.desc().nulls_last(), Vessel.last_ais_update.desc().nulls_last()).limit(per_kind)).scalars().all()
    groups["vessels"] = [
        _hit("vessel", v.id, f"{v.name} ({v.flag_state})", f"MMSI {v.mmsi}{' - IMO ' + v.imo if v.imo else ''} - {v.ship_type or 'type unknown'} - {v.sanctioned_status or 'clear'} - risk {round((v.risk_score or 0) * 100)}%", f"/maritime/vessel/{v.mmsi}",
             status=v.sanctioned_status, risk_score=v.risk_score)
        for v in vessels
    ]

    entities = db.execute(
        select(SanctionsEntity).where(SanctionsEntity.is_active.is_(True), or_(SanctionsEntity.name.ilike(like), SanctionsEntity.imo == q, SanctionsEntity.mmsi == q, cast(SanctionsEntity.aliases, String).ilike(like)))
        .order_by(SanctionsEntity.designation_date.desc().nulls_last()).limit(per_kind)
    ).scalars().all()
    groups["listings"] = [_hit("listing", e.id, e.name, f"{e.designating_authority} - {e.entity_type or 'entity'} - {', '.join(e.programs or [])[:80]}{' - IMO ' + e.imo if e.imo else ''}", f"/sanctions?entity={e.id}", authority=e.designating_authority) for e in entities]

    companies = db.execute(
        select(Company).where(or_(Company.company_name.ilike(like), Company.lei == q.upper(), Company.name_normalized.ilike(like))).order_by(Company.risk_score.desc().nulls_last()).limit(per_kind)
    ).scalars().all()
    groups["companies"] = [_hit("company", c.id, c.company_name, f"{c.registration_country or '?'}{' - LEI ' + c.lei if c.lei else ''} - {c.sanctions_match_type or 'no listing match'}{' - shell' if c.is_shell_company else ''} - risk {round((c.risk_score or 0) * 100)}%", f"/corporate?q={c.company_name}") for c in companies]

    wallets = db.execute(
        select(BlockchainWallet).where(or_(BlockchainWallet.address.ilike(like), BlockchainWallet.owner_name.ilike(like), BlockchainWallet.label.ilike(like))).order_by(BlockchainWallet.balance_usd.desc().nulls_last()).limit(per_kind)
    ).scalars().all()
    groups["wallets"] = [_hit("wallet", w.id, w.address, f"{w.blockchain} - {w.owner_name or w.label or w.wallet_type or 'unlabelled'}{' - ' + w.sanctioning_authority if w.sanctioning_authority else ''} - ${round(w.balance_usd or 0):,}", f"/blockchain?q={w.address}") for w in wallets]

    aircraft = db.execute(
        select(Aircraft).where(or_(Aircraft.registration.ilike(like), Aircraft.icao_hex.ilike(q), Aircraft.operator.ilike(like), Aircraft.owner.ilike(like))).limit(per_kind)
    ).scalars().all()
    groups["aircraft"] = [_hit("aircraft", a.id, a.registration, f"{a.model or 'type unknown'} - {a.operator or a.owner or 'operator unknown'} - {a.country or '?'}{' - ' + a.sanctioning_authority if a.is_sanctioned and a.sanctioning_authority else ''}", "/monitors?tab=aviation") for a in aircraft]

    domains = db.execute(select(InfraAsset).where(or_(InfraAsset.value.ilike(like), InfraAsset.asn_org.ilike(like), InfraAsset.registrar.ilike(like))).limit(per_kind)).scalars().all()
    groups["domains"] = [_hit("domain", d.id, d.value, f"{d.asset_type} - {'live' if d.is_live else 'down'}{' - ' + d.hosting_country if d.hosting_country else ''}{' - ' + d.asn_org if d.asn_org else ''} - risk {round((d.risk_score or 0) * 100)}%", "/monitors?tab=infra") for d in domains]

    events = db.execute(select(GeopoliticalEvent).where(GeopoliticalEvent.title.ilike(like)).order_by(GeopoliticalEvent.event_date.desc()).limit(per_kind)).scalars().all()
    groups["events"] = [_hit("event", e.id, e.title, f"{e.event_type.replace('_', ' ')} - {e.severity} - {', '.join(e.affected_countries or [])} - {e.event_date:%Y-%m-%d %H:%M}Z", "/geopolitical", url=(e.source_urls or [None])[0]) for e in events]

    narratives = db.execute(select(Narrative).where(or_(Narrative.topic.ilike(like), cast(Narrative.keywords, String).ilike(like))).order_by(Narrative.last_seen.desc()).limit(per_kind)).scalars().all()
    groups["narratives"] = [_hit("narrative", n.id, n.topic, f"{n.outlet_count or 0} outlets - {n.item_count or 0} items - {', '.join(n.countries or [])}", "/monitors?tab=narratives") for n in narratives]

    legal = db.execute(select(LegalEvent).where(LegalEvent.title.ilike(like)).order_by(LegalEvent.event_date.desc().nulls_last()).limit(per_kind)).scalars().all()
    groups["legal"] = [_hit("legal", ev.id, ev.title, f"{ev.source.replace('_', ' ')}{' - ' + ev.event_type if ev.event_type else ''}{' - ' + ev.event_date.strftime('%Y-%m-%d') if ev.event_date else ''}", "/monitors?tab=legal", url=ev.url) for ev in legal]

    psc = db.execute(select(PscEvent).where(or_(PscEvent.ship_name.ilike(like), PscEvent.imo == q, PscEvent.company.ilike(like))).order_by(PscEvent.event_date.desc().nulls_last()).limit(per_kind)).scalars().all()
    groups["port_state_control"] = [_hit("psc", p.id, f"{p.ship_name} ({p.flag or '?'})", f"{p.event_type} by {p.source.replace('_', ' ')}{' at ' + p.port if p.port else ''}{' - ' + p.event_date.strftime('%Y-%m-%d') if p.event_date else ''}{' - IMO ' + p.imo if p.imo else ''}", "/monitors?tab=psc") for p in psc]

    total = sum(len(v) for v in groups.values())
    return jsonable({"query": q, "total": total, "groups": {k: v for k, v in groups.items() if v}})
