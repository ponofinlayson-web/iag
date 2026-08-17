"""Data source and account router."""
from __future__ import annotations
import csv
import io
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.core.audit_service import append_audit
from app.models.entitlement import Entitlement
from app.models.identity import Identity, utcnow
from app.models.source import Account, DataSource, SourceType
from app.routers.deps import AnyUser, CertAdminUser, DbSession
router = APIRouter(prefix="/api/sources", tags=["sources"])
PRIVILEGE_LEVELS = {"low", "moderate", "high", "very_high"}
class SourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: str
    description: str | None = None
    owner_employee_id: str | None = None
class LinkIn(BaseModel):
    identity_id: int
class BulkLinkIn(BaseModel):
    match_on: str = Field(pattern="^(username|email)$")
@router.get("")
async def list_sources(db: DbSession, user: AnyUser):
    rows = (await db.execute(select(DataSource).order_by(DataSource.id))).scalars().all()
    out = []
    for s in rows:
        account_count = (
            await db.execute(select(func.count()).select_from(Account).where(Account.data_source_id == s.id))
        ).scalar_one()
        unlinked = (
            await db.execute(
                select(func.count()).select_from(Account).where(
                    Account.data_source_id == s.id, Account.identity_id.is_(None)
                )
            )
        ).scalar_one()
        out.append({
            "id": s.id,
            "name": s.name,
            "source_type": s.source_type.value if s.source_type else None,
            "description": s.description,
            "is_active": s.is_active,
            "account_count": account_count,
            "unlinked_count": unlinked,
        })
    return {"items": out}
@router.post("")
async def create_source(body: SourceIn, db: DbSession, user: CertAdminUser):
    try:
        stype = SourceType(body.source_type)
    except ValueError:
        raise HTTPException(400, "Unsupported source_type")
    dup = (await db.execute(select(DataSource).where(DataSource.name == body.name))).scalars().first()
    if dup:
        raise HTTPException(409, "Source name already exists")
    owner_id = None
    if body.owner_employee_id:
        owner = (
            await db.execute(select(Identity).where(Identity.employee_id == body.owner_employee_id))
        ).scalars().first()
        if owner is None:
            raise HTTPException(400, "Unknown owner")
        owner_id = owner.id
    src = DataSource(name=body.name, source_type=stype, description=body.description, owner_identity_id=owner_id)
    db.add(src)
    await db.flush()
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="source_created", entity_type="data_source", entity_id=src.id,
                       details={"name": src.name, "type": stype.value})
    await db.commit()
    return {"id": src.id, "name": src.name}
@router.get("/{source_id}")
async def get_source(source_id: int, db: DbSession, user: AnyUser):
    s = await db.get(DataSource, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    return {"id": s.id, "name": s.name,
            "source_type": s.source_type.value if s.source_type else None,
            "description": s.description, "is_active": s.is_active}
@router.delete("/{source_id}")
async def delete_source(source_id: int, db: DbSession, user: CertAdminUser):
    s = await db.get(DataSource, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    name = s.name
    await db.delete(s)
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="source_deleted", entity_type="data_source", entity_id=source_id,
                       details={"name": name})
    await db.commit()
    return {"ok": True}
@router.get("/{source_id}/accounts")
async def list_accounts(source_id: int, db: DbSession, user: AnyUser,
                        linked: str = "all", page: int = 1, page_size: int = 50):
    s = await db.get(DataSource, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    filters = [Account.data_source_id == source_id]
    if linked == "unlinked":
        filters.append(Account.identity_id.is_(None))
    elif linked == "linked":
        filters.append(Account.identity_id.is_not(None))
    total = (await db.execute(select(func.count()).select_from(Account).where(*filters))).scalar_one()
    rows = (await db.execute(
        select(Account).where(*filters).order_by(Account.id)
        .offset((page - 1) * page_size).limit(page_size)
    )).scalars().all()
    ent_ids = {a.entitlement_id for a in rows if a.entitlement_id}
    ents = {}
    if ent_ids:
        eres = await db.execute(select(Entitlement).where(Entitlement.id.in_(ent_ids)))
        ents = {e.id: e for e in eres.scalars().all()}
    items = []
    for a in rows:
        e = ents.get(a.entitlement_id)
        items.append({
            "id": a.id,
            "account_value": a.account_value,
            "account_type": a.account_type,
            "identity_id": a.identity_id,
            "entitlement_name": e.name if e else None,
            "privilege_level": a.privilege_level,
            "last_seen_at": a.last_seen_at.isoformat() if a.last_seen_at else None,
        })
    return {"total": total, "page": page, "items": items}
@router.put("/{source_id}/accounts/{account_id}/link")
async def link_account(source_id: int, account_id: int, body: LinkIn, db: DbSession, user: CertAdminUser):
    a = await db.get(Account, account_id)
    if a is None or a.data_source_id != source_id:
        raise HTTPException(404, "Account not found")
    ident = await db.get(Identity, body.identity_id)
    if ident is None:
        raise HTTPException(400, "Unknown identity")
    a.identity_id = ident.id
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="account_linked", entity_type="account", entity_id=account_id,
                       details={"identity_id": ident.id})
    await db.commit()
    return {"ok": True}
@router.post("/{source_id}/accounts/bulk-link")
async def bulk_link(source_id: int, body: BulkLinkIn, db: DbSession, user: CertAdminUser):
    accounts = (
        await db.execute(select(Account).where(
            Account.data_source_id == source_id, Account.identity_id.is_(None)))
    ).scalars().all()
    if body.match_on == "username":
        idents = {
            i.username: i.id
            for i in (await db.execute(select(Identity).where(Identity.username.is_not(None)))).scalars().all()
        }
    else:
        idents = {
            i.email: i.id
            for i in (await db.execute(select(Identity).where(Identity.email.is_not(None)))).scalars().all()
        }
    linked = 0
    for a in accounts:
        ident_id = idents.get(a.account_value)
        if ident_id:
            a.identity_id = ident_id
            linked += 1
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="account_bulk_link", entity_type="data_source", entity_id=source_id,
                       details={"match_on": body.match_on, "linked": linked})
    await db.commit()
    return {"linked": linked, "considered": len(accounts)}
@router.post("/{source_id}/upload")
async def upload_csv(source_id: int, file: UploadFile, db: DbSession, user: CertAdminUser,
                     account_column: str = "account", entitlement_column: str = "entitlement",
                     privilege_column: str = "privilege"):
    """CSV snapshot import: natural-key upsert for entitlements, per-(source,value)
    upsert for accounts. This is v1's best idea, kept intact."""
    s = await db.get(DataSource, source_id)
    if s is None:
        raise HTTPException(404, "Source not found")
    raw = await file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, "File must be UTF-8 CSV")
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None or account_column not in reader.fieldnames:
        raise HTTPException(400, f"CSV must include an {account_column} column")
    if entitlement_column not in (reader.fieldnames or []):
        raise HTTPException(400, f"CSV must include an {entitlement_column} column")
    now = utcnow()
    created_acc, created_ent = 0, 0
    for row in reader:
        account_value = (row.get(account_column) or "").strip()
        if not account_value:
            continue
        ent_name = (row.get(entitlement_column) or "").strip()
        ent = None
        if ent_name:
            natural = ent_name.lower()
            ent = (
                await db.execute(select(Entitlement).where(
                    Entitlement.data_source_id == source_id,
                    Entitlement.source_column == entitlement_column,
                    Entitlement.source_value == natural,
                ))
            ).scalars().first()
            if ent is None:
                seq = (await db.execute(select(func.count()).select_from(Entitlement))).scalar_one() + 1
                ent = Entitlement(
                    data_source_id=source_id,
                    catalog_id=f"ENT-{seq:05d}",
                    name=ent_name,
                    source_column=entitlement_column,
                    source_value=natural,
                    last_seen_at=now,
                )
                db.add(ent)
                await db.flush()
                created_ent += 1
            else:
                ent.last_seen_at = now
        privilege = (row.get(privilege_column) or "").strip().lower() or None
        if privilege and privilege not in PRIVILEGE_LEVELS:
            privilege = None
        acc = (
            await db.execute(select(Account).where(
                Account.data_source_id == source_id, Account.account_value == account_value))
        ).scalars().first()
        if acc is None:
            db.add(Account(
                data_source_id=source_id,
                account_value=account_value,
                account_type="username",
                entitlement_id=ent.id if ent else None,
                privilege_level=privilege,
                last_seen_at=now,
            ))
            created_acc += 1
        else:
            acc.entitlement_id = ent.id if ent else acc.entitlement_id
            acc.privilege_level = privilege or acc.privilege_level
            acc.last_seen_at = now
    await append_audit(db, actor_id=user.id, actor_username=user.identity.username or "",
                       action="source_upload", entity_type="data_source", entity_id=source_id,
                       details={"accounts_created": created_acc, "entitlements_created": created_ent})
    await db.commit()
    return {"accounts_created": created_acc, "entitlements_created": created_ent}
