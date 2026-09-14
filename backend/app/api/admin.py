"""/api/admin/* - operator configuration.

Configuration changes are recorded in the immutable audit log.  There is no
authentication yet (MVP runs on a trusted network behind Cloudflare Tunnel),
so the audit entry attributes the change to ``anonymous``.
"""

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.audit import AuditLog
from app.utils import config_store
from app.utils.logger import logger

router = APIRouter(tags=["admin"])


@router.get("/config")
def get_config() -> dict[str, Any]:
    """Effective configuration (defaults merged with operator overrides)."""
    return config_store.get_config()


@router.post("/config")
def update_config(
    patch: dict[str, Any] = Body(..., description="Partial config; nested sections are deep-merged"),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Merge a partial configuration into the overrides file and return the result."""
    if not patch:
        raise HTTPException(status_code=422, detail="Empty configuration patch")
    try:
        merged = config_store.update_config(patch)
    except KeyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    db.add(
        AuditLog(
            action_type="config_updated",
            user_id="anonymous",
            rationale="Configuration updated via POST /api/admin/config",
            supporting_data={"patch": patch},
            source_systems=["api.admin"],
            created_by="anonymous",
        )
    )
    db.commit()
    logger.bind(component="admin").info("Configuration updated: sections={}", sorted(patch))
    return merged
