"""Domain / IP intelligence (ecosystem tier 3).

Websites named in OFAC listings ("Website www.example.com") become ``InfraAsset``
rows that are footprinted in rotation: RDAP registration data, DNS resolution,
hosting ASN / country and the certificate-transparency subdomain estate.  A
listed party whose domain still resolves on a Western provider is a compliance
lead; a fresh certificate on a dormant domain is a reactivation lead.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.analysis.tier2 import infra_risk
from app.database import SessionLocal
from app.integrations import infra
from app.integrations.infra import extract_domains
from app.models.sanctions import SanctionsEntity
from app.models.tier2 import InfraAsset
from app.utils import config_store
from app.utils.logger import logger
from app.utils.time import utcnow

log = logger.bind(component="infra")


def _config() -> dict[str, Any]:
    return config_store.get_config().get("infra", {})


class InfraBot:
    def __init__(self) -> None:
        self.last_run: dict[str, datetime] = {}
        self.last_result: dict[str, Any] = {}

    def status(self) -> dict[str, Any]:
        return {"last_run": dict(self.last_run), "last_result": self.last_result}

    async def seed(self) -> dict[str, Any]:
        result = await asyncio.to_thread(self._seed)
        self.last_run["seed"] = utcnow()
        self.last_result["seed"] = result
        log.info("seed: {}", result)
        return result

    @staticmethod
    def _seed() -> dict[str, Any]:
        with SessionLocal() as db:
            existing = {v for (v,) in db.execute(select(InfraAsset.value).where(InfraAsset.asset_type == "domain")).all()}
            added = 0
            entities = db.execute(select(SanctionsEntity).where(SanctionsEntity.is_active.is_(True), SanctionsEntity.remarks.like("%Website%"))).scalars().all()
            for entity in entities:
                for domain in extract_domains(entity.remarks):
                    if domain in existing:
                        continue
                    existing.add(domain)
                    db.add(InfraAsset(asset_type="domain", value=domain, entity_id=entity.id, entity_name=entity.name[:300], created_at=utcnow()))
                    added += 1
            db.commit()
            total = db.execute(select(func.count(InfraAsset.id))).scalar() or 0
            return {"added": added, "total": total, "entities_with_websites": len(entities)}

    async def footprint(self) -> dict[str, Any]:
        cfg = _config()
        if not cfg.get("enabled", True):
            return {"skipped": "disabled"}
        batch = int(cfg.get("batch", 15))
        recheck_days = int(cfg.get("recheck_days", 14))
        due = await asyncio.to_thread(self._due, batch, recheck_days)
        result = {"checked": 0, "live": 0, "errors": 0}
        for asset_id, domain in due:
            try:
                record = await infra.footprint(domain)
                live = await asyncio.to_thread(self._apply, asset_id, record)
                result["checked"] += 1
                result["live"] += int(bool(live))
            except Exception as exc:  # noqa: BLE001
                result["errors"] += 1
                log.debug("footprint failed for {}: {}", domain, exc)
                await asyncio.to_thread(self._touch, asset_id)
        self.last_run["footprint"] = utcnow()
        self.last_result["footprint"] = result
        log.info("footprint: {}", result)
        return result

    @staticmethod
    def _due(batch: int, recheck_days: int) -> list[tuple[int, str]]:
        with SessionLocal() as db:
            stale = utcnow() - timedelta(days=recheck_days)
            rows = db.execute(select(InfraAsset.id, InfraAsset.value).where(InfraAsset.asset_type == "domain", or_(InfraAsset.last_checked.is_(None), InfraAsset.last_checked < stale))
                              .order_by(InfraAsset.last_checked.asc().nulls_first()).limit(batch)).all()
            return [(r.id, r.value) for r in rows]

    @staticmethod
    def _touch(asset_id: int) -> None:
        with SessionLocal() as db:
            row = db.get(InfraAsset, asset_id)
            if row:
                row.last_checked = utcnow()
                db.commit()

    @staticmethod
    def _apply(asset_id: int, record: infra.DomainRecord) -> bool:
        with SessionLocal() as db:
            row = db.get(InfraAsset, asset_id)
            if row is None:
                return False
            previously_live = row.is_live
            row.registrar = record.registrar
            row.registered_at = record.registered_at
            row.expires_at = record.expires_at
            row.nameservers = record.nameservers
            row.resolves_to = record.resolves_to
            row.asn, row.asn_org, row.hosting_country = record.asn, record.asn_org, record.hosting_country
            row.certificate_count = record.certificate_count
            row.certificate_names = record.certificate_names[:100]
            row.is_live = record.is_live
            score, findings = infra_risk(record.registrar, record.hosting_country, record.is_live, record.certificate_count, record.nameservers, bool(row.entity_id))
            if previously_live is False and record.is_live:
                findings.append("reactivated: resolved again after being dead")
                score = min(1.0, score + 0.2)
            row.findings = findings
            row.risk_score = score
            row.last_checked = utcnow()
            db.commit()
            return bool(record.is_live)

    @staticmethod
    def summary(db: Session) -> dict[str, Any]:
        total = db.execute(select(func.count(InfraAsset.id))).scalar() or 0
        checked = db.execute(select(func.count(InfraAsset.id)).where(InfraAsset.last_checked.is_not(None))).scalar() or 0
        live = db.execute(select(func.count(InfraAsset.id)).where(InfraAsset.is_live.is_(True))).scalar() or 0
        by_country = db.execute(select(InfraAsset.hosting_country, func.count()).where(InfraAsset.hosting_country.is_not(None)).group_by(InfraAsset.hosting_country).order_by(func.count().desc()).limit(10)).all()
        by_asn = db.execute(select(InfraAsset.asn_org, func.count()).where(InfraAsset.asn_org.is_not(None)).group_by(InfraAsset.asn_org).order_by(func.count().desc()).limit(10)).all()
        return {"assets": total, "checked": checked, "live": live, "hosting_countries": [{"country": c, "assets": n} for c, n in by_country], "hosting_providers": [{"provider": a, "assets": n} for a, n in by_asn]}


infra_bot = InfraBot()
