"""Identity router: CRUD, CSV import/export."""
from __future__ import annotations
import csv
import io
from typing import Annotated
from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from app.core.audit_service import append_audit
from app.models.identity import Identity
from app.models.user import Role
from app.routers.deps import AnyUser, CertAdminUser, DbSession
router = APIRouter(prefix="/api/identities", tags=["identities"])
IDENTITY_FIELDS = (
    "employee_id", "username", "email", "first_name", "last_name",
    "department", "job_title",
)
class IdentityIn(BaseModel):
    employee_id: str = Field(min_length=1, max_length=100)
    username: str | None = None
    email: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    department: str | None = None
    job_title: str | None = None
    manager_employee_id: str | None = None
    is_active: bool = True
class IdentityOut(BaseModel):
    id: int
    employee_id: str
    username: str | None
    email: str | None
    first_name: str | None
    last_name: str | None
    department: str | None
    job_title: str | None = None
    manager_id: int | None
    is_active: bool
    source: str | None
    model_config = {"from_attributes": True}
async def _resolve_manager(db, manager_employee_id: str | None) -> int | None:
    if not manager_employee_id:
        return None
    m = (
        await db.execute(
            select(Identity).where(Identity.employee_id == manager_employee_id)
        )
    ).scalars().first()
    if m is None:
        raise HTTPException(400, f"Unknown manager_employee_id {manager_employee_id}")
    return m.id
async def _check_cycle(db: DbSession, identity_id: int, new_manager_id: int | None) -> None:
    """Walk up the manager chain from new_manager; if we reach identity_id, reject."""
    seen = set()
    current = new_manager_id
    while current is not None and current not in seen:
        if current == identity_id:
            raise HTTPException(400, "Manager cycle detected")
        seen.add(current)
        row = (await db.execute(select(Identity.manager_id).where(Identity.id == current))).scalar_one_or_none()
        current = row
@router.get("")
async def list_identities(
    db: DbSession,
    user: AnyUser,
    q: str = "",
    department: str = "",
    page: int = 1,
    page_size: int = 50,
):
    filters = [Identity.is_active == True]  # noqa: E712
    if q:
        like = f"%{q.lower()}%"
        filters.append(
            or_(
                func.lower(Identity.employee_id).like(like),
                func.lower(Identity.username).like(like),
                func.lower(Identity.email).like(like),
                func.lower(Identity.last_name).like(like),
            )
        )
    if department:
        filters.append(Identity.department == department)
    total = (
        await db.execute(select(func.count()).select_from(Identity).where(*filters))
    ).scalar_one()
    rows = (
        await db.execute(
            select(Identity)
            .where(*filters)
            .order_by(Identity.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "total": total,
        "page": page,
        "items": [IdentityOut.model_validate(r).model_dump() for r in rows],
    }
@router.get("/export")
async def export_identities(db: DbSession, user: AnyUser):
    rows = (await db.execute(select(Identity).order_by(Identity.id))).scalars().all()
    def gen():
        buf = io.StringIO()
        w = csv.writer(buf)
        w.writerow(["employee_id", "username", "email", "first_name", "last_name",
                    "department", "job_title", "manager_employee_id", "is_active", "source"])
        manager_ids = {r.id: r.employee_id for r in rows}
        for r in rows:
            mgr = None
            if r.manager_id:
                mgr = manager_ids.get(r.manager_id)
            w.writerow([r.employee_id, r.username, r.email, r.first_name, r.last_name,
                        r.department, r.job_title, mgr, r.is_active, r.source])
        yield buf.getvalue()
    return StreamingResponse(gen(), media_type="text/csv")
@router.get("/{identity_id}")
async def get_identity(identity_id: int, db: DbSession, user: AnyUser):
    ident = await db.get(Identity, identity_id)
    if ident is None:
        raise HTTPException(404, "Identity not found")
    return IdentityOut.model_validate(ident).model_dump()
@router.post("")
async def create_identity(body: IdentityIn, db: DbSession, user: CertAdminUser):
    dup = (
        await db.execute(select(Identity).where(Identity.employee_id == body.employee_id))
    ).scalars().first()
    if dup:
        raise HTTPException(409, f"employee_id {body.employee_id} already exists")
    manager_id = await _resolve_manager(db, body.manager_employee_id)
    ident = Identity(
        employee_id=body.employee_id,
        username=body.username,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        department=body.department,
        job_title=body.job_title,
        manager_id=manager_id,
        is_active=body.is_active,
        source="manual",
    )
    db.add(ident)
    await db.flush()
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="identity_created",
        entity_type="identity",
        entity_id=ident.id,
        details={"employee_id": ident.employee_id},
    )
    await db.commit()
    return IdentityOut.model_validate(ident).model_dump()
@router.put("/{identity_id}")
async def update_identity(identity_id: int, body: IdentityIn, db: DbSession, user: CertAdminUser):
    ident = await db.get(Identity, identity_id)
    if ident is None:
        raise HTTPException(404, "Identity not found")
    if body.employee_id != ident.employee_id:
        clash = (
            await db.execute(select(Identity).where(Identity.employee_id == body.employee_id))
        ).scalars().first()
        if clash:
            raise HTTPException(409, "employee_id already in use")
        ident.employee_id = body.employee_id
    manager_id = await _resolve_manager(db, body.manager_employee_id)
    await _check_cycle(db, identity_id, manager_id)
    ident.username = body.username
    ident.email = body.email
    ident.first_name = body.first_name
    ident.last_name = body.last_name
    ident.department = body.department
    ident.job_title = body.job_title
    ident.manager_id = manager_id
    ident.is_active = body.is_active
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="identity_updated",
        entity_type="identity",
        entity_id=identity_id,
        details={"employee_id": ident.employee_id},
    )
    await db.commit()
    return IdentityOut.model_validate(ident).model_dump()
@router.delete("/{identity_id}")
async def delete_identity(identity_id: int, db: DbSession, user: CertAdminUser):
    ident = await db.get(Identity, identity_id)
    if ident is None:
        raise HTTPException(404, "Identity not found")
    employee_id = ident.employee_id
    await db.delete(ident)
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="identity_deleted",
        entity_type="identity",
        entity_id=identity_id,
        details={"employee_id": employee_id},
    )
    await db.commit()
    return {"ok": True}
@router.post("/import")
async def import_identities(file: UploadFile, db: DbSession, user: CertAdminUser):
    """CSV import with upsert-by-employee_id semantics and full row report."""
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 CSV")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or "employee_id" not in reader.fieldnames:
        raise HTTPException(400, "CSV must include an employee_id column")
    created, updated, errors = 0, 0, []
    for lineno, row in enumerate(reader, start=2):
        employee_id = (row.get("employee_id") or "").strip()
        if not employee_id:
            errors.append({"line": lineno, "error": "empty employee_id"})
            continue
        manager_id = None
        mgr_key = (row.get("manager_employee_id") or "").strip()
        if mgr_key:
            m = (
                await db.execute(
                    select(Identity).where(Identity.employee_id == mgr_key)
                )
            ).scalars().first()
            if m is None:
                errors.append({"line": lineno, "error": f"unknown manager {mgr_key}"})
                continue
            manager_id = m.id
        existing = (
            await db.execute(
                select(Identity).where(Identity.employee_id == employee_id)
            )
        ).scalars().first()
        if existing:
            existing.username = (row.get("username") or "").strip() or existing.username
            existing.email = (row.get("email") or "").strip() or existing.email
            existing.first_name = (row.get("first_name") or "").strip() or existing.first_name
            existing.last_name = (row.get("last_name") or "").strip() or existing.last_name
            existing.department = (row.get("department") or "").strip() or existing.department
            existing.job_title = (row.get("job_title") or "").strip() or existing.job_title
            existing.manager_id = manager_id if manager_id else existing.manager_id
            updated += 1
        else:
            db.add(Identity(
                employee_id=employee_id,
                username=(row.get("username") or "").strip() or None,
                email=(row.get("email") or "").strip() or None,
                first_name=(row.get("first_name") or "").strip() or None,
                last_name=(row.get("last_name") or "").strip() or None,
                department=(row.get("department") or "").strip() or None,
                job_title=(row.get("job_title") or "").strip() or None,
                manager_id=manager_id,
                source="csv",
            ))
            # flush so later rows can resolve this identity as manager
            await db.flush()
            created += 1
    await append_audit(
        db,
        actor_id=user.id,
        actor_username=user.identity.username or "",
        action="identity_import",
        entity_type="identity",
        entity_id=None,
        details={"created": created, "updated": updated, "errors": len(errors)},
    )
    await db.commit()
    return {"created": created, "updated": updated, "errors": errors}
