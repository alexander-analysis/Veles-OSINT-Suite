"""Corporate intelligence bot (ecosystem bot 6) - who owns the companies behind the sanctions lists.

* ``seed_companies`` - every sanctioned company and every vessel owner named on the
  lists becomes a ``Company`` row (no external calls).
* ``enrich_companies`` - GLEIF search for each seed in rotation; on a confident name
  match the LEI record is attached and the ownership tree walked (direct / ultimate
  parent, direct children).  Parents and subsidiaries are screened against the
  sanctions index, so an unlisted subsidiary of a listed parent surfaces as
  sanctions exposure.  Shell / opacity indicators and risk scores are computed
  for every company touched.  SEC EDGAR adds SIC / CIK for US-registered entities.
* ``ingest_lei`` - analyst-initiated import of a specific LEI (from the search UI).
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.corporate import assess_shell, best_match, clean_company_name, company_risk, core_name, latin_enough, ownership_risk
from app.database import SessionLocal
from app.integrations import edgar, gleif
from app.integrations.sanctions_common import normalize_name
from app.models.audit import AuditLog
from app.models.corporate import Company, OwnershipChain, Shareholder
from app.models.maritime import Vessel
from app.models.sanctions import SanctionsEntity
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="corporate")

ORIGIN_PRIORITY = {"analyst_search": 0, "vessel_owner": 1, "sanctions_seed": 2, "ownership_walk": 3}


def _config() -> dict[str, Any]:
    return config_store.get_config().get("corporate", {})


class CorporateBot:
    def __init__(self) -> None:
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}
        self.enriching = False

    def status(self) -> dict[str, Any]:
        return {"last_run": dict(self.last_run), "last_result": self.last_result, "enriching": self.enriching}

    # ---------------------------------------------------------------- seeding
    async def seed_companies(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._seed)
        self.last_run["seed"] = utcnow()
        self.last_result["seed"] = result
        log.info("seed: {}", result)
        return result

    @staticmethod
    def _seed() -> dict[str, Any]:
        with SessionLocal() as db:
            known = {n for (n,) in db.execute(select(Company.name_normalized)).all()}
            rows: list[dict[str, Any]] = []
            now = utcnow()
            # executemany needs identical keys in every row
            template: dict[str, Any] = {"registration_country": None, "source_ref": None, "sanctioned_entity_id": None, "sanctions_match_type": None, "sanctions_confidence": None, "registered_address": None}
            # OFAC first so the English spelling wins when several authorities list the same company
            order = {"OFAC": 0, "UN": 1, "EU": 2}
            entities = sorted(db.execute(select(SanctionsEntity).where(SanctionsEntity.is_active.is_(True), SanctionsEntity.entity_type == "company")).scalars().all(),
                              key=lambda e: order.get(e.designating_authority, 3))
            for entity in entities:
                norm = normalize_name(entity.name)[:300]
                if not norm or norm in known or not latin_enough(entity.name):
                    continue
                known.add(norm)
                rows.append({
                    **template, "company_name": clean_company_name(entity.name), "name_normalized": norm, "registration_country": entity.country_linked, "source": "sanctions_list",
                    "source_ref": f"{entity.designating_authority}:{entity.source_id}", "linked_to_sanctioned": True, "sanctioned_entity_id": entity.id, "sanctions_match_type": "direct",
                    "sanctions_confidence": 1.0, "risk_score": company_risk(True, "direct", None, entity.country_linked), "origin": "sanctions_seed", "is_shell_company": False,
                    "ownership_opaque": False, "is_active": True, "registered_address": (entity.addresses or [None])[0] if isinstance(entity.addresses, list) and entity.addresses else None,
                    "created_at": now, "updated_at": now,
                })
            owners = db.execute(select(SanctionsEntity.vessel_owner, func.min(SanctionsEntity.id)).where(SanctionsEntity.is_active.is_(True), SanctionsEntity.vessel_owner.is_not(None)).group_by(SanctionsEntity.vessel_owner)).all()
            for owner, entity_id in owners:
                norm = normalize_name(owner)[:300]
                if not norm or norm in known:
                    continue
                known.add(norm)
                rows.append({
                    **template, "company_name": clean_company_name(owner), "name_normalized": norm, "source": "sanctions_list", "source_ref": f"vessel_owner:{entity_id}", "linked_to_sanctioned": True,
                    "sanctioned_entity_id": entity_id, "sanctions_match_type": "vessel_owner", "sanctions_confidence": 0.9, "risk_score": company_risk(True, "vessel_owner", None, None),
                    "origin": "vessel_owner", "is_shell_company": False, "ownership_opaque": False, "is_active": True, "created_at": now, "updated_at": now,
                })
            ais_owners = db.execute(select(Vessel.owner_name).where(Vessel.owner_name.is_not(None)).distinct().limit(2000)).all()
            for (owner,) in ais_owners:
                norm = normalize_name(owner)[:300]
                if not norm or norm in known:
                    continue
                known.add(norm)
                rows.append({**template, "company_name": clean_company_name(owner), "name_normalized": norm, "source": "ais", "linked_to_sanctioned": False, "risk_score": 0.1, "origin": "vessel_owner",
                             "is_shell_company": False, "ownership_opaque": False, "is_active": True, "created_at": now, "updated_at": now})
            if rows:
                db.execute(Company.__table__.insert(), rows)
                db.commit()
            total = db.execute(select(func.count(Company.id))).scalar() or 0
            return {"inserted": len(rows), "total": total}

    # ------------------------------------------------------------- enrichment
    async def enrich_companies(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True) or self.enriching:
            return {"skipped": "disabled" if not cfg.get("enabled", True) else "running"}
        self.enriching = True
        try:
            batch = int(cfg.get("enrich_batch", 40))
            reenrich_days = int(cfg.get("reenrich_days", 30))
            due = await asyncio.to_thread(self._due, batch, reenrich_days)
            result = {"checked": 0, "matched": 0, "walked": 0, "exposure_found": 0, "errors": 0}
            for company_id, name in due:
                try:
                    outcome = await self.enrich_one(company_id, name)
                    result["checked"] += 1
                    result["matched"] += outcome.get("matched", 0)
                    result["walked"] += outcome.get("walked", 0)
                    result["exposure_found"] += outcome.get("exposure", 0)
                except Exception as exc:  # noqa: BLE001 - keep walking
                    result["errors"] += 1
                    log.warning("enrichment failed for {}: {}", name, exc)
                    await asyncio.to_thread(self._touch, company_id, "error")
            self.last_run["enrich"] = utcnow()
            self.last_result["enrich"] = result
            log.info("enrichment: {}", result)
            return result
        finally:
            self.enriching = False

    @staticmethod
    def _due(batch: int, reenrich_days: int) -> list[tuple[int, str]]:
        with SessionLocal() as db:
            stale = utcnow() - timedelta(days=reenrich_days)
            rows = db.execute(
                select(Company.id, Company.company_name, Company.origin)
                .where(or_(Company.last_enriched.is_(None), Company.last_enriched < stale), Company.origin != "ownership_walk")
                .order_by(Company.last_enriched.asc().nulls_first(), Company.id.desc())
                .limit(batch * 3)
            ).all()
        rows.sort(key=lambda r: ORIGIN_PRIORITY.get(r.origin, 5))
        return [(r.id, r.company_name) for r in rows[:batch]]

    @staticmethod
    def _touch(company_id: int, note: str) -> None:
        with SessionLocal() as db:
            company = db.get(Company, company_id)
            if company:
                company.last_enriched = utcnow()
                db.commit()

    @staticmethod
    def _query_names(company_id: int, name: str) -> list[str]:
        """The listed name plus the aliases the sanctions authority published (GLEIF often holds the English alias, not the transliteration)."""
        names = [name]
        with SessionLocal() as db:
            company = db.get(Company, company_id)
            entity = db.get(SanctionsEntity, company.sanctioned_entity_id) if company and company.sanctioned_entity_id else None
            for alias in (entity.aliases or []) if entity else []:
                if isinstance(alias, str) and alias.strip() and alias.strip().upper() != name.upper():
                    names.append(alias.strip())
        return names[:6]

    async def enrich_one(self, company_id: int, name: str) -> dict[str, int]:
        cfg = _config()
        min_similarity = float(cfg.get("min_name_similarity", 0.9))
        names = await asyncio.to_thread(self._query_names, company_id, name)
        match = None

        def _best(pool: list[gleif.LeiRecord]) -> tuple[int, float] | None:
            found = None
            for query in names:
                hit = best_match(query, [(c.name, c.other_names) for c in pool], min_similarity)
                if hit and (found is None or hit[1] > found[1]):
                    found = hit
            return found

        # Legal-name filter first (cheap, precise); the full-text index also covers other-language names such as
        # a Cyrillic legal name whose English alias is what the sanctions list carries.
        query = core_name(name) if len(core_name(name)) >= 3 else name  # "JOINT STOCK COMPANY SOVCOMFLOT" -> "SOVCOMFLOT"
        candidates = await gleif.search(query, limit=10)
        match = _best(candidates)
        if match is None:
            more = await gleif.search(query, limit=10, fulltext=True)
            if not more and len(names) > 1:
                more = await gleif.search(core_name(names[1]) or names[1], limit=10, fulltext=True)
            seen = {c.lei for c in candidates}
            candidates = candidates + [c for c in more if c.lei not in seen]
            match = _best(candidates)
        if match is None:
            edgar_hit = await self._edgar(name) if cfg.get("edgar_enabled", True) else None
            await asyncio.to_thread(self._apply_no_lei, company_id, edgar_hit)
            return {"matched": 0}
        record = candidates[match[0]]
        return await self.ingest_record(record, company_id=company_id, similarity=match[1])

    async def ingest_lei(self, lei: str, analyst: str | None = None) -> dict[str, Any]:
        record = await gleif.record(lei)
        if record is None:
            return {"error": "LEI not found"}
        outcome = await self.ingest_record(record, origin="analyst_search")
        with SessionLocal() as db:
            company = db.execute(select(Company).where(Company.lei == lei)).scalar_one_or_none()
            db.add(AuditLog(action_type="company_lookup", user_id=analyst or "analyst", rationale=f"Imported {record.name} ({lei}) from GLEIF with ownership walk",
                            supporting_data={"lei": lei, **outcome}, source_systems=["api.corporate", "gleif"], created_by=analyst or "analyst"))
            db.commit()
            return {"company_id": company.id if company else None, **outcome}

    async def ingest_record(self, record: gleif.LeiRecord, company_id: int | None = None, similarity: float | None = None, origin: str = "sanctions_seed") -> dict[str, int]:
        """Attach a GLEIF record to a company (creating it if needed) and walk its ownership tree."""
        cfg = _config()
        direct = await gleif.parent(record.lei)
        ultimate = await gleif.parent(record.lei, ultimate=True)
        children = await gleif.children(record.lei, limit=int(cfg.get("max_children", 50)))
        edgar_hit = await self._edgar(record.name) if cfg.get("edgar_enabled", True) and (record.country == "US" or record.jurisdiction == "US") else None
        return await asyncio.to_thread(self._apply_record, record, company_id, similarity, origin, direct, ultimate, children, edgar_hit)

    @staticmethod
    async def _edgar(name: str) -> edgar.EdgarCompany | None:
        try:
            hits = await edgar.lookup_company(name, count=5)
        except Exception as exc:  # noqa: BLE001
            log.debug("edgar lookup failed for {}: {}", name, exc)
            return None
        match = best_match(name, [(h.name, []) for h in hits], 0.92)
        return hits[match[0]] if match else None

    # ------------------------------------------------------------ persistence
    @staticmethod
    def _apply_no_lei(company_id: int, edgar_hit: edgar.EdgarCompany | None) -> None:
        with SessionLocal() as db:
            company = db.get(Company, company_id)
            if company is None:
                return
            company.last_enriched = utcnow()
            if edgar_hit:
                company.source_ref = company.source_ref or f"edgar:{edgar_hit.cik}"
                company.industry_sector = edgar_hit.sic_description or company.industry_sector
                company.business_address = edgar_hit.business_address or company.business_address
                company.website = edgar_hit.filings_url
            shell = assess_shell(company.registration_country, None, None, None, None, company.company_name, 0, utcnow(), company.linked_to_sanctioned)
            company.shell_indicators = shell.indicators
            company.shell_company_confidence = shell.confidence
            company.is_shell_company = shell.is_shell
            company.risk_score = company_risk(company.linked_to_sanctioned, company.sanctions_match_type, shell.confidence, company.registration_country)
            db.commit()

    @staticmethod
    def _upsert(db: Session, record: gleif.LeiRecord, origin: str, now: datetime) -> Company:
        """Find the company for a GLEIF record (by LEI, then by normalized name) or create it, then refresh its registry fields."""
        company = db.execute(select(Company).where(Company.lei == record.lei)).scalar_one_or_none()
        if company is None:
            norm = normalize_name(record.name)[:300]
            company = db.execute(select(Company).where(Company.name_normalized == norm, Company.lei.is_(None))).scalar_one_or_none()
        if company is None:
            company = Company(company_name=clean_company_name(record.name), name_normalized=normalize_name(record.name)[:300], origin=origin, source="gleif", created_at=now)
            db.add(company)
        CorporateBot._fill(company, record, now)
        db.flush()
        return company

    @staticmethod
    def _fill(company: Company, record: gleif.LeiRecord, now: datetime) -> Company:
        company.lei = record.lei
        if not company.linked_to_sanctioned or company.origin == "ownership_walk":
            # registry spelling; prefer a Latin alias over a Cyrillic / Greek legal name so analysts can read the tree
            latin = record.name if latin_enough(record.name) else next((n for n in record.other_names if latin_enough(n)), record.name)
            company.company_name = clean_company_name(latin)
        company.registration_country = record.country or company.registration_country
        company.registration_authority = record.jurisdiction
        company.registration_date = record.creation_date
        company.company_type = (record.legal_form or "")[:150] or None
        company.entity_category = record.category
        company.entity_status = record.status
        company.registration_status = record.registration_status
        company.registered_address = ", ".join(filter(None, [record.address, record.city, record.country]))[:500] or None
        company.source = company.source if company.source == "sanctions_list" else "gleif"
        company.source_ref = company.source_ref or f"gleif:{record.lei}"
        company.is_active = record.status != "INACTIVE"
        company.updated_at = now
        return company

    @staticmethod
    def _screen(name: str) -> tuple[int | None, float]:
        """Sanctions-index lookup for a parent / subsidiary name."""
        try:
            from app.bots.sanctions import sanctions_bot

            matches = sanctions_bot.check_entity(name, "company", 0.92)
        except Exception:  # noqa: BLE001 - index not built yet
            return None, 0.0
        if not matches:
            return None, 0.0
        best = max(matches, key=lambda m: m.confidence)
        return (best.entity.id if best.entity else None), best.confidence

    @classmethod
    def _screen_any(cls, names: list[str]) -> tuple[int | None, float]:
        for candidate in names:
            if not candidate or not latin_enough(candidate):
                continue
            entity_id, confidence = cls._screen(candidate)
            if entity_id:
                return entity_id, confidence
        return None, 0.0

    def _apply_record(self, record, company_id, similarity, origin, direct, ultimate, children, edgar_hit) -> dict[str, int]:
        now = utcnow()
        exposure = 0
        with SessionLocal() as db:
            company = db.get(Company, company_id) if company_id else None
            if company is not None:
                existing_lei = db.execute(select(Company).where(Company.lei == record.lei, Company.id != company.id)).scalar_one_or_none()
                if existing_lei is not None:
                    # the same legal entity was already created by an ownership walk - merge the sanctions link onto it
                    existing_lei.linked_to_sanctioned = existing_lei.linked_to_sanctioned or company.linked_to_sanctioned
                    existing_lei.sanctioned_entity_id = existing_lei.sanctioned_entity_id or company.sanctioned_entity_id
                    existing_lei.sanctions_match_type = company.sanctions_match_type if company.linked_to_sanctioned else existing_lei.sanctions_match_type
                    existing_lei.sanctions_confidence = max(existing_lei.sanctions_confidence or 0, company.sanctions_confidence or 0) or None
                    existing_lei.origin = company.origin
                    company.last_enriched = now
                    company.lei = None
                    db.delete(company)
                    company = existing_lei
                else:
                    company.lei = record.lei
            company = self._upsert(db, record, origin, now) if company is None else self._fill(company, record, now)
            company.last_enriched = now
            if not company.linked_to_sanctioned:
                # analyst imports / walked parents arrive unlinked - screen the registry names against the lists
                entity_id, confidence = self._screen_any([record.name, *record.other_names[:5]])
                if entity_id:
                    company.linked_to_sanctioned, company.sanctioned_entity_id, company.sanctions_match_type, company.sanctions_confidence = True, entity_id, "direct", confidence
            if similarity is not None:
                company.source_ref = f"gleif:{record.lei} ({similarity:.2f})"  # documents how confidently the LEI was attached
            if edgar_hit:
                company.industry_sector = edgar_hit.sic_description or company.industry_sector
                company.business_address = edgar_hit.business_address or company.business_address
                company.website = edgar_hit.filings_url
            chain: list[dict[str, Any]] = [{"name": company.company_name, "lei": company.lei, "country": company.registration_country, "relationship": "subject"}]
            exception_reason = None
            involves_sanctioned = bool(company.linked_to_sanctioned)
            involves_shell = False
            # --- parents
            for rel, kind in ((direct, "direct_parent"), (ultimate, "ultimate_parent")):
                if isinstance(rel, gleif.ReportingException):
                    if kind == "direct_parent":
                        exception_reason = rel.reason
                    continue
                if rel is None or (kind == "ultimate_parent" and isinstance(direct, gleif.LeiRecord) and direct.lei == rel.lei):
                    continue
                parent = self._upsert(db, rel, "ownership_walk", now)
                entity_id, confidence = self._screen_any([rel.name, *rel.other_names[:5]])
                if entity_id and not parent.linked_to_sanctioned:
                    parent.linked_to_sanctioned, parent.sanctioned_entity_id, parent.sanctions_match_type, parent.sanctions_confidence = True, entity_id, "direct", confidence
                if parent.linked_to_sanctioned:
                    involves_sanctioned = True
                    if not company.linked_to_sanctioned:
                        company.linked_to_sanctioned, company.sanctioned_entity_id = True, parent.sanctioned_entity_id
                        company.sanctions_match_type, company.sanctions_confidence = ("parent" if kind == "direct_parent" else "ultimate_parent"), round((parent.sanctions_confidence or 0.9) * (0.9 if kind == "direct_parent" else 0.75), 2)
                        exposure += 1
                self._link(db, company, parent, kind, now)
                chain.append({"name": parent.company_name, "lei": parent.lei, "country": parent.registration_country, "relationship": kind, "sanctioned": bool(parent.linked_to_sanctioned)})
            # --- children
            for child_record in children:
                child = self._upsert(db, child_record, "ownership_walk", now)
                entity_id, confidence = self._screen_any([child_record.name, *child_record.other_names[:3]])
                if entity_id and not child.linked_to_sanctioned:
                    child.linked_to_sanctioned, child.sanctioned_entity_id, child.sanctions_match_type, child.sanctions_confidence = True, entity_id, "direct", confidence
                if company.linked_to_sanctioned and not child.linked_to_sanctioned:
                    child.linked_to_sanctioned, child.sanctioned_entity_id, child.sanctions_match_type = True, company.sanctioned_entity_id, "parent"
                    child.sanctions_confidence = round((company.sanctions_confidence or 0.9) * 0.9, 2)
                    exposure += 1
                if child.linked_to_sanctioned and not company.linked_to_sanctioned and child.sanctions_match_type == "direct":
                    company.linked_to_sanctioned, company.sanctioned_entity_id, company.sanctions_match_type, company.sanctions_confidence = True, child.sanctioned_entity_id, "child", 0.5
                    exposure += 1
                    involves_sanctioned = True
                self._link(db, child, company, "direct_parent", now)
                child_shell = assess_shell(child.registration_country, child.registration_status, child.entity_status, child.registration_date, None, child.company_name, 0, now, child.linked_to_sanctioned)
                child.shell_indicators, child.shell_company_confidence, child.is_shell_company = child_shell.indicators, child_shell.confidence, child_shell.is_shell
                child.risk_score = company_risk(child.linked_to_sanctioned, child.sanctions_match_type, child_shell.confidence, child.registration_country)
            # --- shell / opacity and risk for the subject
            shell = assess_shell(company.registration_country, company.registration_status, company.entity_status, company.registration_date, exception_reason, company.company_name, len(children), now, company.linked_to_sanctioned)
            company.shell_indicators, company.shell_company_confidence, company.is_shell_company = shell.indicators, shell.confidence, shell.is_shell
            company.ownership_opaque, company.parent_reporting_exception = shell.opaque, exception_reason
            company.risk_score = company_risk(company.linked_to_sanctioned, company.sanctions_match_type, shell.confidence, company.registration_country)
            involves_shell = shell.is_shell
            # --- ownership chain
            db.execute(OwnershipChain.__table__.delete().where(OwnershipChain.subsidiary_id == company.id))
            top = chain[-1]
            db.add(OwnershipChain(subsidiary_id=company.id, subsidiary_name=company.company_name, ultimate_owner_name=top["name"], ultimate_owner_type="company" if top["lei"] else "unknown",
                                  ultimate_owner_lei=top["lei"], ultimate_owner_country=top["country"], chain_length=len(chain) - 1, chain_path=chain, involves_sanctioned=involves_sanctioned,
                                  involves_shell_companies=involves_shell, involves_secrecy_jurisdiction=any(h.get("country") in {"VG", "KY", "PA", "MH", "LR", "SC", "BZ", "AE", "CY", "MT", "HK", "SG", "LU", "CH"} for h in chain),
                                  risk_score=ownership_risk(chain, involves_sanctioned, involves_shell), computed_at=now))
            if exposure:
                db.add(AuditLog(action_type="sanctions_exposure_found", user_id="system", rationale=f"{exposure} related compan(ies) of {company.company_name} linked to a sanctioned party through ownership",
                                supporting_data={"company_id": company.id, "lei": company.lei, "chain": chain}, source_systems=["bots.corporate", "gleif"], created_by="system"))
            db.commit()
        return {"matched": 1, "walked": 1 + len(children) + sum(isinstance(r, gleif.LeiRecord) for r in (direct, ultimate)), "exposure": exposure}

    @staticmethod
    def _link(db: Session, child: Company, parent: Company, relationship: str, now: datetime) -> None:
        existing = db.execute(select(Shareholder).where(Shareholder.company_id == child.id, Shareholder.shareholder_company_id == parent.id, Shareholder.relationship_type == relationship)).scalar_one_or_none()
        if existing is None:
            db.add(Shareholder(company_id=child.id, shareholder_name=parent.company_name, shareholder_type="company", relationship_type=relationship, shareholder_company_id=parent.id,
                               shareholder_lei=parent.lei, country=parent.registration_country, is_sanctioned=bool(parent.linked_to_sanctioned and parent.sanctions_match_type == "direct"),
                               sanctioned_entity_id=parent.sanctioned_entity_id if parent.linked_to_sanctioned else None, is_beneficial_owner=relationship == "ultimate_parent", source="gleif", created_at=now))
        else:
            existing.is_sanctioned = bool(parent.linked_to_sanctioned and parent.sanctions_match_type == "direct")
            existing.sanctioned_entity_id = parent.sanctioned_entity_id if parent.linked_to_sanctioned else None

    # ---------------------------------------------------------------- summary
    @staticmethod
    def summary(db: Session) -> dict[str, Any]:
        total = db.execute(select(func.count(Company.id))).scalar() or 0
        with_lei = db.execute(select(func.count(Company.id)).where(Company.lei.is_not(None))).scalar() or 0
        enriched = db.execute(select(func.count(Company.id)).where(Company.last_enriched.is_not(None))).scalar() or 0
        by_match = dict(db.execute(select(Company.sanctions_match_type, func.count()).where(Company.linked_to_sanctioned.is_(True)).group_by(Company.sanctions_match_type)).all())
        shells = db.execute(select(func.count(Company.id)).where(Company.is_shell_company.is_(True))).scalar() or 0
        opaque = db.execute(select(func.count(Company.id)).where(Company.ownership_opaque.is_(True))).scalar() or 0
        chains = db.execute(select(func.count(OwnershipChain.id))).scalar() or 0
        chains_sanctioned = db.execute(select(func.count(OwnershipChain.id)).where(OwnershipChain.involves_sanctioned.is_(True))).scalar() or 0
        top_countries = db.execute(select(Company.registration_country, func.count()).where(Company.linked_to_sanctioned.is_(True), Company.registration_country.is_not(None)).group_by(Company.registration_country).order_by(func.count().desc()).limit(10)).all()
        return {
            "companies": total,
            "with_lei": with_lei,
            "enriched": enriched,
            "linked_by_match_type": by_match,
            "exposure": sum(n for k, n in by_match.items() if k in ("parent", "ultimate_parent", "child", "shareholder", "director")),
            "shell_companies": shells,
            "opaque_ownership": opaque,
            "ownership_chains": chains,
            "chains_with_sanctioned": chains_sanctioned,
            "top_countries": [{"country": c, "companies": n} for c, n in top_countries],
        }


corporate_bot = CorporateBot()
