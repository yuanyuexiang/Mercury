"""线索后台 API（技术方案 §10）：列表/详情/导出/人工修正（自动重算评分）/手动同步。"""

import csv
import io
from datetime import UTC, datetime
from typing import Any

import structlog
from domain import repositories, scoring
from domain.models import Lead, User
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from api.deps import AdminRead, AdminWrite

router = APIRouter(prefix="/api/leads", tags=["leads"])
logger = structlog.get_logger()

PAGE_SIZE = 20

EDITABLE_FIELDS = (
    "name",
    "company",
    "country",
    "business_email",
    "requirement",
    "team_size",
    "budget_range",
    "purchase_timeline",
    "notes",
    "status",
)


def _lead_out(lead: Lead, user: User | None = None) -> dict[str, Any]:
    return {
        "id": lead.id,
        "conversation_id": lead.conversation_id,
        **repositories.lead_to_dict(lead),
        "score_reasons": lead.score_reasons,
        "status": lead.status,
        "version": lead.version,
        "external_crm_id": lead.external_crm_id,
        "updated_at": lead.updated_at.isoformat(),
        "user": (
            {"username": user.username, "telegram_user_id": user.telegram_user_id} if user else None
        ),
    }


def _filtered(grade: str | None, status: str | None, sort: str) -> Any:
    stmt = select(Lead)
    if sort == "recent":
        stmt = stmt.order_by(Lead.updated_at.desc())
    else:
        stmt = stmt.order_by(Lead.score.desc(), Lead.updated_at.desc())
    if grade:
        stmt = stmt.where(Lead.grade == grade)
    if status:
        stmt = stmt.where(Lead.status == status)
    return stmt


@router.get("", dependencies=AdminRead)
async def list_leads(
    request: Request,
    grade: str | None = Query(default=None),
    status: str | None = Query(default=None),
    sort: str = Query(default="score"),
    page: int = Query(default=1, ge=1),
) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        stmt = _filtered(grade, status, sort)
        total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar()
        leads = (
            (await session.execute(stmt.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)))
            .scalars()
            .all()
        )
        items = []
        for lead in leads:
            user = await session.get(User, lead.user_id)
            items.append(_lead_out(lead, user))
    return {"items": items, "total": total, "page": page, "page_size": PAGE_SIZE}


EXPORT_COLUMNS = (
    ("id", "Lead ID"),
    ("name", "姓名"),
    ("company", "公司"),
    ("business_email", "邮箱"),
    ("country", "国家"),
    ("requirement", "需求"),
    ("team_size", "团队规模"),
    ("budget_range", "预算"),
    ("purchase_timeline", "采购时间"),
    ("score", "评分"),
    ("grade", "等级"),
    ("status", "状态"),
    ("updated_at", "更新时间"),
)

EXPORT_LIMIT = 5000


@router.get("/export", dependencies=AdminRead)
async def export_csv(
    request: Request,
    grade: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> Response:
    """CSV 导出（同列表筛选，上限 5000 行）：销售离线跟进用。"""
    async with request.app.state.session_factory() as session:
        leads = (
            (await session.execute(_filtered(grade, status, "score").limit(EXPORT_LIMIT)))
            .scalars()
            .all()
        )
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([label for _, label in EXPORT_COLUMNS])
        for lead in leads:
            row = {**repositories.lead_to_dict(lead), "id": lead.id, "score": lead.score}
            row["grade"] = lead.grade
            row["status"] = lead.status
            row["updated_at"] = lead.updated_at.isoformat()
            writer.writerow(
                [row.get(key) if row.get(key) is not None else "" for key, _ in EXPORT_COLUMNS]
            )
    filename = f"leads-{datetime.now(UTC).strftime('%Y%m%d')}.csv"
    return Response(
        content="﻿" + buf.getvalue(),  # BOM：Excel 直接打开不乱码
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{lead_id}", dependencies=AdminRead)
async def get_lead(request: Request, lead_id: int) -> dict[str, Any]:
    async with request.app.state.session_factory() as session:
        lead = await session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404)
        user = await session.get(User, lead.user_id)
    return _lead_out(lead, user)


class LeadPatch(BaseModel):
    name: str | None = None
    company: str | None = None
    country: str | None = None
    business_email: str | None = None
    requirement: str | None = None
    team_size: str | None = None
    budget_range: str | None = None
    purchase_timeline: str | None = None
    notes: str | None = None
    status: str | None = None


async def _create_and_enqueue_sync(request: Request, session: Any, lead: Lead) -> int | None:
    new_version = lead.version + 1
    await repositories.update_lead(session, lead.id, {"version": new_version})
    job_id = await repositories.create_integration_job(
        session,
        integration_type="google_sheets",
        entity_type="lead",
        entity_id=lead.id,
        idempotency_key=f"sheets:lead:{lead.id}:v{new_version}",
        payload={"trigger": "admin"},
    )
    await session.commit()
    if job_id is not None:
        await request.app.state.arq.enqueue_job("sync_lead", job_id, None)
    return job_id


@router.patch("/{lead_id}", dependencies=AdminWrite)
async def patch_lead(request: Request, lead_id: int, body: LeadPatch) -> dict[str, Any]:
    """人工修正字段 → 自动重算评分（§10），并触发一次同步。"""
    async with request.app.state.session_factory() as session:
        lead = await session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404)
        updates = {
            field: value
            for field, value in body.model_dump(exclude_unset=True).items()
            if field in EDITABLE_FIELDS
        }
        for field, value in updates.items():
            await repositories.add_audit(
                session,
                "admin",
                "lead_field_update",
                "lead",
                lead.id,
                {"field": field, "old": getattr(lead, field), "new": value},
            )
        merged = {**repositories.lead_to_dict(lead), **updates}
        result = scoring.score_lead(merged)
        updates.update(score=result.score, grade=result.grade, score_reasons=result.reasons)
        await repositories.update_lead(session, lead.id, updates)
        await session.commit()
        await _create_and_enqueue_sync(request, session, lead)
        await session.refresh(lead)
        return _lead_out(lead)


@router.post("/{lead_id}/sync", dependencies=AdminWrite)
async def manual_sync(request: Request, lead_id: int) -> dict[str, Any]:
    """手动重试同步（§10）：版本 +1 建新任务并立即入队。"""
    async with request.app.state.session_factory() as session:
        lead = await session.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(status_code=404)
        job_id = await _create_and_enqueue_sync(request, session, lead)
    return {"job_id": job_id}
