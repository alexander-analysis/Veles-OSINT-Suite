"""/api/corporate/* - companies, ownership chains, sanctions exposure, live GLEIF search."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.bots.corporate import corporate_bot
from app.bots.runtime import bot_loop
from app.bots.sanctions import sanctions_bot
from app.database import get_db
from app.integrations import gleif
from app.models.corporate import Company, CompanyDirector, OwnershipChain, Shareholder
from app.models.sanctions import SanctionsEntity
from app.schemas.corporate import (
    CompaniesResponse,
    CompanyDetail,
    CompanyOut,
    DirectorOut,
    IngestRequest,
    LeiSearchHit,
    LeiSearchResponse,
    OwnershipChainOut,
    RelatedCompany,
    SanctionedRef,
    ShareholderOut,
)
from app.utils.serialization import jsonable

router = APIRouter(tags=["corporate"])


@router.get("/companies", response_model=CompaniesResponse)
def list_companies(
    q: str | None = Query(None, max_length=200, description="Name / LEI substring"),
    country: str | None = Query(None, max_length=3),
    linked: bool | None = Query(None, description="Linked to a sanctioned party (any match type)"),
    match_type: str | None = Query(None, description="direct, parent, ultimate_parent, child, vessel_owner"),
    exposure_only: bool = Query(False, description="Only indirect links: parent / ultimate_parent / child (not listed themselves)"),
    shell: bool | None = None,
    opaque: bool | None = None,
    has_lei: bool | None = None,
    origin: str | None = None,
    min_risk: float | None = Query(None, ge=0, le=1),
    sort: str = Query("risk", pattern="^(risk|name|updated|enriched)$"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> CompaniesResponse:
    query = select(Company)
    if q:
        pattern = f"%{q}%"
        query = query.where(or_(Company.company_name.ilike(pattern), Company.lei.ilike(pattern), Company.registered_address.ilike(pattern)))
    if country:
        query = query.where(Company.registration_country == country.upper())
    if linked is not None:
        query = query.where(Company.linked_to_sanctioned.is_(linked))
    if match_type:
        query = query.where(Company.sanctions_match_type == match_type)
    if exposure_only:
        query = query.where(Company.linked_to_sanctioned.is_(True), Company.sanctions_match_type.in_(["parent", "ultimate_parent", "child", "shareholder", "director"]))
    if shell is not None:
        query = query.where(Company.is_shell_company.is_(shell))
    if opaque is not None:
        query = query.where(Company.ownership_opaque.is_(opaque))
    if has_lei is True:
        query = query.where(Company.lei.is_not(None))
    elif has_lei is False:
        query = query.where(Company.lei.is_(None))
    if origin:
        query = query.where(Company.origin == origin)
    if min_risk is not None:
        query = query.where(Company.risk_score >= min_risk)
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    order = {"risk": Company.risk_score.desc().nulls_last(), "name": Company.company_name.asc(), "updated": Company.updated_at.desc(), "enriched": Company.last_enriched.desc().nulls_last()}[sort]
    rows = db.execute(query.order_by(order, Company.id).limit(limit).offset(offset)).scalars().all()
    return CompaniesResponse(total=total, limit=limit, offset=offset, filters={"q": q, "country": country, "linked": linked, "match_type": match_type, "exposure_only": exposure_only, "shell": shell, "opaque": opaque, "sort": sort},
                             companies=[CompanyOut.model_validate(r) for r in rows])


def _related(db: Session, company: Company) -> tuple[list[RelatedCompany], list[RelatedCompany]]:
    parents = []
    for sh in company.shareholders:
        if sh.shareholder_company_id:
            parent = db.get(Company, sh.shareholder_company_id)
            if parent:
                parents.append(RelatedCompany(id=parent.id, company_name=parent.company_name, lei=parent.lei, registration_country=parent.registration_country, relationship=sh.relationship_type or "parent",
                                              linked_to_sanctioned=parent.linked_to_sanctioned, sanctions_match_type=parent.sanctions_match_type, risk_score=parent.risk_score))
    subs = []
    rows = db.execute(select(Shareholder, Company).join(Company, Company.id == Shareholder.company_id).where(Shareholder.shareholder_company_id == company.id)).all()
    for sh, child in rows:
        subs.append(RelatedCompany(id=child.id, company_name=child.company_name, lei=child.lei, registration_country=child.registration_country, relationship=sh.relationship_type or "subsidiary",
                                   linked_to_sanctioned=child.linked_to_sanctioned, sanctions_match_type=child.sanctions_match_type, risk_score=child.risk_score))
    return parents, subs


@router.get("/companies/{company_id}", response_model=CompanyDetail)
def company_detail(company_id: int, db: Session = Depends(get_db)) -> CompanyDetail:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    parents, subs = _related(db, company)
    chain = db.execute(select(OwnershipChain).where(OwnershipChain.subsidiary_id == company.id).order_by(OwnershipChain.computed_at.desc())).scalars().first()
    entity = db.get(SanctionsEntity, company.sanctioned_entity_id) if company.sanctioned_entity_id else None
    directors = db.execute(select(CompanyDirector).where(CompanyDirector.company_id == company.id)).scalars().all()
    return CompanyDetail(
        company=CompanyOut.model_validate(company),
        shareholders=[ShareholderOut.model_validate(s) for s in company.shareholders],
        directors=[DirectorOut.model_validate(d) for d in directors],
        subsidiaries=subs,
        parents=parents,
        ownership_chain=OwnershipChainOut.model_validate(chain) if chain else None,
        sanctioned_entity=SanctionedRef(id=entity.id, name=entity.name, designating_authority=entity.designating_authority, programs=entity.programs, entity_type=entity.entity_type) if entity else None,
        gleif_url=f"https://search.gleif.org/#/record/{company.lei}" if company.lei else None,
    )


@router.get("/exposure", response_model=CompaniesResponse)
def exposure(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> CompaniesResponse:
    """Companies that are not listed themselves but sit under / above a listed party in the ownership tree."""
    query = select(Company).where(Company.linked_to_sanctioned.is_(True), Company.sanctions_match_type.in_(["parent", "ultimate_parent", "child", "shareholder", "director"]))
    total = db.execute(select(func.count()).select_from(query.subquery())).scalar() or 0
    rows = db.execute(query.order_by(Company.sanctions_confidence.desc().nulls_last(), Company.risk_score.desc().nulls_last()).limit(limit)).scalars().all()
    return CompaniesResponse(total=total, limit=limit, offset=0, filters={"exposure_only": True}, companies=[CompanyOut.model_validate(r) for r in rows])


@router.get("/chains", response_model=list[OwnershipChainOut])
def list_chains(sanctioned_only: bool = False, limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)) -> list[OwnershipChainOut]:
    query = select(OwnershipChain)
    if sanctioned_only:
        query = query.where(OwnershipChain.involves_sanctioned.is_(True))
    rows = db.execute(query.order_by(OwnershipChain.risk_score.desc().nulls_last(), OwnershipChain.chain_length.desc(), OwnershipChain.computed_at.desc()).limit(limit)).scalars().all()
    return [OwnershipChainOut.model_validate(r) for r in rows]


@router.get("/search", response_model=LeiSearchResponse)
async def search_lei(q: str = Query(min_length=2, max_length=200), live: bool = Query(True, description="Query GLEIF (false = tracked companies only)"), db: Session = Depends(get_db)) -> LeiSearchResponse:
    """Live GLEIF search; each hit shows whether VELES already tracks it and whether the name screens against the sanctions lists."""
    hits: list[LeiSearchHit] = []
    if live:
        records = await gleif.search(q, limit=15, fulltext=True)
        leis = [r.lei for r in records]
        tracked = {c.lei: c.id for c in db.execute(select(Company).where(Company.lei.in_(leis))).scalars()} if leis else {}
        for r in records:
            try:
                screened = len(sanctions_bot.check_entity(r.name, "company", 0.9))
            except Exception:  # noqa: BLE001 - index not built yet
                screened = 0
            hits.append(LeiSearchHit(lei=r.lei, name=r.name, other_names=r.other_names[:5], country=r.country, jurisdiction=r.jurisdiction, status=r.status, registration_status=r.registration_status,
                                     category=r.category, creation_date=r.creation_date, city=r.city, tracked_company_id=tracked.get(r.lei), sanctions_hits=screened))
    else:
        for c in db.execute(select(Company).where(Company.company_name.ilike(f"%{q}%")).limit(15)).scalars():
            hits.append(LeiSearchHit(lei=c.lei or "", name=c.company_name, country=c.registration_country, status=c.entity_status, registration_status=c.registration_status, tracked_company_id=c.id,
                                     sanctions_hits=1 if c.linked_to_sanctioned else 0))
    return LeiSearchResponse(query=q, live=live, hits=hits)


@router.post("/ingest", status_code=202)
def ingest(body: IngestRequest) -> dict[str, Any]:
    """Import an LEI (plus parents / subsidiaries) on the bot loop; poll /companies?q=<lei>."""
    bot_loop.submit(corporate_bot.ingest_lei(body.lei.upper(), body.analyst))
    return {"status": "started", "lei": body.lei.upper()}


@router.get("/summary")
def summary(db: Session = Depends(get_db)) -> dict[str, Any]:
    return jsonable(corporate_bot.summary(db))


@router.get("/status")
def get_status() -> dict[str, Any]:
    return jsonable(corporate_bot.status())


@router.post("/refresh", status_code=202)
def trigger_refresh(job: str = Query("all", pattern="^(all|seed|enrich)$")) -> dict[str, Any]:
    jobs = {"seed": corporate_bot.seed_companies, "enrich": corporate_bot.enrich_companies}
    selected = list(jobs) if job == "all" else [job]
    for name in selected:
        bot_loop.submit(jobs[name]())
    return {"status": "started", "jobs": selected}
