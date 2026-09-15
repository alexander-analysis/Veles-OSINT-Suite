"""Analyst watchlists: follow a vessel, listed party, company, wallet, aircraft, domain or keyword and collect every hit."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.bots.runtime import bot_loop
from app.bots.watchlist import KINDS, watchlist_bot
from app.database import get_db
from app.models.audit import AuditLog
from app.models.maritime import Vessel
from app.models.sanctions import SanctionsEntity
from app.models.watchlist import WatchlistHit, WatchlistItem
from app.schemas.common import APIModel
from app.utils.serialization import jsonable
from app.utils.time import utcnow

router = APIRouter(tags=["watchlist"])


class WatchlistItemIn(APIModel):
    kind: str = Field(pattern="^(vessel|entity|company|wallet|aircraft|domain|keyword)$")
    key: str = Field(min_length=1, max_length=300)
    label: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=500)
    alert: bool = True
    created_by: str = Field("analyst", max_length=100)


class WatchlistItemPatch(APIModel):
    label: str | None = Field(None, max_length=300)
    note: str | None = Field(None, max_length=500)
    alert: bool | None = None
    active: bool | None = None


class WatchlistItemOut(APIModel):
    id: int
    kind: str
    key: str
    label: str | None = None
    note: str | None = None
    created_by: str | None = None
    created_at: datetime
    active: bool
    alert: bool
    last_checked_at: datetime | None = None
    last_hit_at: datetime | None = None
    hit_count: int
    recent_hits: int = 0
    href: str | None = None


class WatchlistHitOut(APIModel):
    id: int
    item_id: int
    record_type: str
    record_id: int
    timestamp: datetime
    severity: str | None = None
    summary: str | None = None
    href: str | None = None
    created_at: datetime
    item_label: str | None = None
    item_kind: str | None = None
    item_key: str | None = None


def _href(item: WatchlistItem) -> str | None:
    return {"vessel": f"/maritime/vessel/{item.key}", "entity": f"/sanctions?entity={item.key}", "company": f"/corporate?q={item.key}", "wallet": f"/blockchain?q={item.key}",
            "aircraft": "/monitors?tab=aviation", "domain": "/monitors?tab=infra", "keyword": f"/search?q={item.key}"}.get(item.kind)


def _normalise(kind: str, key: str, db: Session) -> tuple[str, str | None]:
    """Canonical key (MMSI digits, entity id, upper-case registration / LEI, lower-case domain) and a default label."""
    key = key.strip()
    if kind == "vessel":
        vessel = db.execute(select(Vessel).where((Vessel.mmsi == key) | (Vessel.imo == key) | (Vessel.name.ilike(key)))).scalars().first()
        if vessel is None:
            raise HTTPException(status_code=404, detail="No tracked vessel with that MMSI, IMO or name")
        return vessel.mmsi, f"{vessel.name} ({vessel.flag_state})"
    if kind == "entity":
        entity = db.get(SanctionsEntity, int(key)) if key.isdigit() else db.execute(select(SanctionsEntity).where(SanctionsEntity.name.ilike(key), SanctionsEntity.is_active.is_(True))).scalars().first()
        if entity is None:
            raise HTTPException(status_code=404, detail="No listing with that id or name")
        return str(entity.id), f"{entity.name} ({entity.designating_authority})"
    if kind == "aircraft":
        return key.upper(), None
    if kind == "domain":
        return key.lower(), None
    return key, None


@router.get("", response_model=list[WatchlistItemOut])
def list_items(include_inactive: bool = False, db: Session = Depends(get_db)) -> list[WatchlistItemOut]:
    query = select(WatchlistItem)
    if not include_inactive:
        query = query.where(WatchlistItem.active.is_(True))
    items = db.execute(query.order_by(WatchlistItem.last_hit_at.desc().nulls_last(), WatchlistItem.created_at.desc())).scalars().all()
    week = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    recent = dict(db.execute(select(WatchlistHit.item_id, func.count()).where(WatchlistHit.created_at >= week.fromordinal(week.toordinal() - 7)).group_by(WatchlistHit.item_id)).all())
    totals = dict(db.execute(select(WatchlistHit.item_id, func.count()).group_by(WatchlistHit.item_id)).all())  # live count: hits can be purged with their records
    out = []
    for item in items:
        row = WatchlistItemOut.model_validate(item)
        row.recent_hits = recent.get(item.id, 0)
        row.hit_count = totals.get(item.id, 0)
        row.href = _href(item)
        out.append(row)
    return out


@router.post("", response_model=WatchlistItemOut, status_code=201)
def add_item(payload: WatchlistItemIn, db: Session = Depends(get_db)) -> WatchlistItemOut:
    if payload.kind not in KINDS:
        raise HTTPException(status_code=422, detail="unknown kind")
    key, default_label = _normalise(payload.kind, payload.key, db)
    item = db.execute(select(WatchlistItem).where(WatchlistItem.kind == payload.kind, WatchlistItem.key == key)).scalar_one_or_none()
    if item is None:
        item = WatchlistItem(kind=payload.kind, key=key, label=payload.label or default_label or key, note=payload.note, alert=payload.alert, created_by=payload.created_by, created_at=utcnow(), active=True, hit_count=0)
        db.add(item)
        db.add(AuditLog(action_type="watchlist_added", user_id=payload.created_by, rationale=f"watch {payload.kind} {key} ({item.label})", supporting_data={"kind": payload.kind, "key": key, "note": payload.note}, source_systems=["api.watchlist"], created_by=payload.created_by))
    else:
        item.active, item.alert = True, payload.alert
        if payload.label:
            item.label = payload.label
        if payload.note:
            item.note = payload.note
    db.commit()
    db.refresh(item)
    bot_loop.submit(watchlist_bot.check(item.id))  # first pass fills in the last week of context
    row = WatchlistItemOut.model_validate(item)
    row.href = _href(item)
    return row


@router.patch("/{item_id}", response_model=WatchlistItemOut)
def update_item(item_id: int, payload: WatchlistItemPatch, db: Session = Depends(get_db)) -> WatchlistItemOut:
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    row = WatchlistItemOut.model_validate(item)
    row.href = _href(item)
    return row


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, db: Session = Depends(get_db)) -> None:
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    db.add(AuditLog(action_type="watchlist_removed", user_id="analyst", rationale=f"stop watching {item.kind} {item.key} ({item.label})", supporting_data={"kind": item.kind, "key": item.key, "hits": item.hit_count}, source_systems=["api.watchlist"], created_by="analyst"))
    db.delete(item)
    db.commit()


@router.get("/hits", response_model=list[WatchlistHitOut])
def list_hits(item_id: int | None = None, severity: str | None = None, limit: int = Query(100, ge=1, le=1000), db: Session = Depends(get_db)) -> list[WatchlistHitOut]:
    query = select(WatchlistHit, WatchlistItem).join(WatchlistItem, WatchlistItem.id == WatchlistHit.item_id)
    if item_id is not None:
        query = query.where(WatchlistHit.item_id == item_id)
    if severity:
        query = query.where(WatchlistHit.severity.in_(severity.split(",")))
    rows = db.execute(query.order_by(WatchlistHit.timestamp.desc()).limit(limit)).all()
    out = []
    for hit, item in rows:
        row = WatchlistHitOut.model_validate(hit)
        row.item_label, row.item_kind, row.item_key = item.label, item.kind, item.key
        out.append(row)
    return out


@router.get("/summary")
def summary(days: int = Query(7, ge=1, le=365), db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable({**watchlist_bot.summary(db, days), "status": watchlist_bot.status()})


@router.post("/check", status_code=202)
def run_check() -> dict[str, Any]:
    bot_loop.submit(watchlist_bot.check())
    return {"status": "started"}


@router.get("/lookup")
def lookup(kind: str, key: str, db: Session = Depends(get_db)) -> dict[str, Any]:
    """Is this thing already watched? (used by the watch buttons)"""
    if kind not in KINDS:
        raise HTTPException(status_code=422, detail="unknown kind")
    try:
        canonical, _ = _normalise(kind, key, db)
    except HTTPException:
        return {"watched": False, "item": None}
    item = db.execute(select(WatchlistItem).where(WatchlistItem.kind == kind, WatchlistItem.key == canonical, WatchlistItem.active.is_(True))).scalar_one_or_none()
    return jsonable({"watched": item is not None, "item": WatchlistItemOut.model_validate(item).model_dump() if item else None})
