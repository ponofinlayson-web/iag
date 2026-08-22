"""SCIM 2.0 protocol surface (feature 6, part 1): /api/scim/v2.

Bearer-token only - a single installation token, SHA-256 at rest. The
whole surface answers 503 while it is off (enabled=false or no token):
an IdP polling a cold installation gets an explicit "not provisioned"
instead of an auth puzzle. Every failure renders an RFC 7644 error
envelope. Writes append one hash-chained audit entry (actor_username
"scim") in the same transaction; reads never audit (house rule; v1's
SCIMEvent read logging was noise). Management endpoints (config/token)
are session-auth and land here in Phase C.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy import func, or_, select

from app.core.apikeys import hash_key, verify_key
from app.core.audit_service import append_audit
from app.core.scim import (
    PAGE_DEFAULT_COUNT,
    PAGE_MAX_COUNT,
    ScimError,
    identity_to_scim,
    normalize_patch,
    parse_filter,
    scim_to_identity_fields,
    service_provider_config,
)
from app.db import get_db
from app.models.identity import Identity
from app.models.scim import ScimSettings
from sqlalchemy.ext.asyncio import AsyncSession

DbSession = Annotated[AsyncSession, Depends(get_db)]

_FILTER_COLUMNS = {
    "userName": Identity.username,
    "emails.value": Identity.email,
    "externalId": Identity.employee_id,
}
_WRITABLE_FIELDS = (
    "username", "email", "first_name", "last_name", "job_title", "department", "is_active",
)


async def require_scim_token(request: Request, db: DbSession) -> None:
    """SCIM bearer gate: one installation token, constant-time compare.

    503 while the surface is off (enabled=false or token_hash null -
    two deliberate admin acts); 401 + WWW-Authenticate on a missing or
    wrong token. SCIM tokens are their own credential class: the
    /api/api-keys choke in deps.py never sees them, and they carry no
    ApiKey role semantics.
    """
    row = await db.get(ScimSettings, 1)
    enabled = False
    token_hash: str | None = None
    if row is not None:
        try:
            enabled = bool(row.config_dict().get("enabled"))
        except ValueError:
            enabled = False
        token_hash = row.token_hash
    if not enabled or token_hash is None:
        raise ScimError(503, "SCIM provisioning is not enabled on this installation")
    auth = request.headers.get("authorization", "")
    presented = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not presented or not verify_key(presented, token_hash):
        raise ScimError(
            401,
            "Invalid SCIM bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


router = APIRouter(prefix="/api/scim/v2", tags=["scim"],
                   dependencies=[Depends(require_scim_token)])


async def _get_by_scim_id(db: AsyncSession, scim_id: str) -> Identity:
    ident = (
        await db.execute(select(Identity).where(Identity.employee_id == scim_id))
    ).scalars().first()
    if ident is None:
        raise ScimError(404, f"User {scim_id} not found")
    return ident


async def _assert_unique(
    db: AsyncSession,
    *,
    username: str | None = None,
    email: str | None = None,
    employee_id: str | None = None,
    exclude_id: int | None = None,
) -> None:
    """Protocol-level 409 instead of a constraint 500 (spec: an IdP
    re-pushing an existing user must get a protocol answer it can
    recover from)."""
    clauses = []
    if username:
        clauses.append(Identity.username == username)
    if email:
        clauses.append(Identity.email == email)
    if employee_id:
        clauses.append(Identity.employee_id == employee_id)
    if not clauses:
        return
    query = select(Identity).where(or_(*clauses))
    if exclude_id is not None:
        query = query.where(Identity.id != exclude_id)
    hit = (await db.execute(query.limit(1))).scalars().first()
    if hit is None:
        return
    if username and hit.username == username:
        attribute = "userName"
    elif employee_id and hit.employee_id == employee_id:
        attribute = "externalId"
    else:
        attribute = "email"
    raise ScimError(409, f"{attribute} already exists")


def _validate_lengths(username: str | None, email: str | None, external_id: str | None) -> None:
    if username and len(username) > 100:
        raise ScimError(400, "userName must be at most 100 characters")
    if email and len(email) > 255:
        raise ScimError(400, "email must be at most 255 characters")
    if external_id and len(external_id) > 100:
        raise ScimError(400, "externalId must be at most 100 characters")


async def _audit_scim_write(db: AsyncSession, ident: Identity, action: str, operation: str) -> None:
    await append_audit(
        db,
        actor_id=None,
        actor_username="scim",
        action=action,
        entity_type="identity",
        entity_id=ident.id,
        details={
            "operation": operation,
            "userName": ident.username,
            "externalId": ident.employee_id,
            "active": bool(ident.is_active),
        },
    )


@router.get("/ServiceProviderConfig")
async def get_service_provider_config():
    return service_provider_config()


@router.get("/Users")
async def list_users(
    db: DbSession,
    startIndex: int = Query(1),
    count: int = Query(PAGE_DEFAULT_COUNT),
    filter: str | None = Query(None),
):
    if startIndex < 1:
        raise ScimError(400, "startIndex must be >= 1")
    parsed = parse_filter(filter)
    where = _FILTER_COLUMNS[parsed[0]] == parsed[1] if parsed else None

    total_query = select(func.count()).select_from(Identity)
    rows_query = select(Identity).order_by(Identity.id)
    if where is not None:
        total_query = total_query.where(where)
        rows_query = rows_query.where(where)
    total = (await db.execute(total_query)).scalar_one()
    rows = (
        await db.execute(
            rows_query.offset(startIndex - 1).limit(max(0, min(count, PAGE_MAX_COUNT)))
        )
    ).scalars().all()
    return {
        "totalResults": total,
        "startIndex": startIndex,
        "itemsPerPage": len(rows),
        "Resources": [identity_to_scim(r) for r in rows],
    }


@router.get("/Users/{scim_id}")
async def get_user(scim_id: str, db: DbSession):
    return identity_to_scim(await _get_by_scim_id(db, scim_id))


@router.post("/Users", status_code=201)
async def create_user(body: dict, db: DbSession):
    user_name = body.get("userName")
    if not isinstance(user_name, str) or not user_name.strip():
        raise ScimError(400, "userName is required")
    external_id = body.get("externalId")
    if not isinstance(external_id, str) or not external_id.strip():
        raise ScimError(400, "externalId is required (it becomes the employee_id join key)")
    _validate_lengths(user_name, None, external_id)
    fields = scim_to_identity_fields(body)
    _validate_lengths(None, fields.get("email"), None)
    await _assert_unique(
        db, username=fields.get("username"), email=fields.get("email"), employee_id=external_id
    )
    ident = Identity(
        employee_id=external_id,
        source="scim",
        **{k: v for k, v in fields.items() if k in _WRITABLE_FIELDS},
    )
    db.add(ident)
    await db.flush()
    await _audit_scim_write(db, ident, "scim_user_created", "create")
    await db.commit()
    return identity_to_scim(ident)


@router.put("/Users/{scim_id}")
async def replace_user(scim_id: str, body: dict, db: DbSession):
    ident = await _get_by_scim_id(db, scim_id)
    payload_external_id = body.get("externalId")
    if payload_external_id is not None and payload_external_id != scim_id:
        raise ScimError(
            400, "externalId disagrees with the path id (employee_id is the immutable join key)"
        )
    user_name = body.get("userName")
    if not isinstance(user_name, str) or not user_name.strip():
        raise ScimError(400, "PUT requires userName (full-resource replace)")
    _validate_lengths(user_name, None, None)
    fields = scim_to_identity_fields(body)
    _validate_lengths(None, fields.get("email"), None)
    await _assert_unique(
        db, username=fields.get("username"), email=fields.get("email"), exclude_id=ident.id
    )
    for key, value in fields.items():
        setattr(ident, key, value)
    await _audit_scim_write(db, ident, "scim_user_replaced", "replace")
    await db.commit()
    return identity_to_scim(ident)


@router.patch("/Users/{scim_id}")
async def patch_user(scim_id: str, body: dict, db: DbSession):
    ident = await _get_by_scim_id(db, scim_id)
    fields = scim_to_identity_fields(normalize_patch(body))
    if fields:
        _validate_lengths(fields.get("username"), fields.get("email"), None)
        await _assert_unique(
            db, username=fields.get("username"), email=fields.get("email"), exclude_id=ident.id
        )
        for key, value in fields.items():
            setattr(ident, key, value)
        await _audit_scim_write(db, ident, "scim_user_patched", "patch")
        await db.commit()
    return identity_to_scim(ident)


@router.delete("/Users/{scim_id}", status_code=204)
async def delete_user(scim_id: str, db: DbSession):
    """Soft deprovision, always (D2). Idempotent on retries: the value is
    re-set and the retry still audits - the IdP retried, and the record
    should say so."""
    ident = await _get_by_scim_id(db, scim_id)
    ident.is_active = False
    await _audit_scim_write(db, ident, "scim_user_deprovisioned", "deprovision")
    await db.commit()
    return Response(status_code=204)
