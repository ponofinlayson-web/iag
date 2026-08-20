"""Live connector adapters (Feature 2 Phase C): ldap / entra / sql.

Shared contract (SPECS/feature-2-connectors.md, Adapters): every adapter
exposes `async fetch(config: dict, secret: str) -> SyncSnapshot` plus a
SYNCHRONOUS `validate(config, secret)` for fail-fast at config-save time
(the validate_smtp philosophy: misconfig dies at write, not at 03:00 in
the worker). Network libs run through asyncio.to_thread where sync.

Config keys (JSON blob in DataSource.connector_config; secret lives in
connector_secret — plaintext by user decision 2026-08-20):

- ldap:  url (ldap://host:389 | ldaps://...), base_dn, bind_dn (opt),
         filter (default "(objectClass=person)"), account_attr (default
         sAMAccountName), entitlements_attr (default memberOf; DN CN
         component becomes the entitlement name).
- entra: tenant_id, client_id (secret = client secret). Paginated
         /users + per-user transitiveMemberOf groups -> entitlements.
         Token is client-credentials, cached in-process.
- sql:   url (sync DSN; async DSNs and the literal "$SECRET" placeholder
         in the URL are translated), query (a SELECT returning columns
         account / entitlement [/ privilege], long format — the worker
         merges rows per account). Runs on a throwaway engine inside a
         READ ONLY transaction on Postgres.

csv/xlsx have no adapter: get_adapter raises, manual sync must 400.
"""
from __future__ import annotations

import asyncio
import re
import time
from urllib.parse import quote

import httpx
from sqlalchemy import create_engine, text

from app.core.sync_worker import AccountRecord, SyncSnapshot

DEFAULT_TIMEOUT = 30.0


def _timeout(config: dict) -> float:
    try:
        return float(config.get("timeout_seconds") or DEFAULT_TIMEOUT)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT


def _first_value(attrs: dict, *names: str) -> str | None:
    """Case-insensitive lookup of the first non-empty value; ldap3
    attribute dicts hold lists, raw rows hold scalars."""
    lower = {k.lower(): v for k, v in attrs.items()}
    for name in names:
        v = lower.get(name.lower())
        values = v if isinstance(v, (list, tuple)) else [v]
        for item in values:
            if item is not None and str(item).strip():
                return str(item).strip()
    return None


# --------------------------------------------------------------- LDAP

LDAP_PAGE_SIZE = 500
_PAGED_OID = "1.2.840.113556.1.4.319"  # simple paged results control
_CN_RE = re.compile(r"^\s*cn=([^,]+)", re.IGNORECASE)


def _ldap_connect(config: dict, secret: str, timeout: float):
    from ldap3 import Connection, Server

    server = Server(config["url"], connect_timeout=timeout)
    # auto_bind=True raises on bad credentials at connect time.
    return Connection(
        server,
        user=config.get("bind_dn") or None,
        password=secret,
        auto_bind=True,
        receive_timeout=timeout,
        read_only=True,
    )


def _dn_to_name(dn: str) -> str:
    m = _CN_RE.match(dn or "")
    return (m.group(1) if m else (dn or "").strip()).strip()


def _ldap_base(config: dict) -> str:
    base = (config.get("base_dn") or config.get("base") or "").strip()
    if not base:
        raise ValueError("ldap config missing base_dn")
    if not (config.get("url") or "").strip():
        raise ValueError("ldap config missing url")
    return base


def _ldap_fetch_sync(config: dict, secret: str, timeout: float) -> SyncSnapshot:
    base = _ldap_base(config)
    search_filter = config.get("filter") or "(objectClass=person)"
    account_attr = config.get("account_attr") or "sAMAccountName"
    ents_attr = (config.get("entitlements_attr") or "memberOf").lower()
    conn = _ldap_connect(config, secret, timeout)
    accounts: list[AccountRecord] = []
    try:
        cookie = None
        pages = 0
        while True:
            conn.search(
                base, search_filter, attributes=["*"],
                paged_size=LDAP_PAGE_SIZE, paged_cookie=cookie,
            )
            page_len = len(conn.entries)
            for entry in conn.entries:
                attrs = entry.entry_attributes_as_dict
                value = _first_value(
                    attrs, account_attr, "userPrincipalName", "mail",
                ) or entry.entry_dn
                if not value.strip():
                    continue
                lower_attrs = {k.lower(): v for k, v in attrs.items()}
                raw_groups = lower_attrs.get(ents_attr) or []
                groups = raw_groups if isinstance(raw_groups, (list, tuple)) else [raw_groups]
                accounts.append(AccountRecord(
                    value=value,
                    account_type="username",
                    entitlements=tuple(dict.fromkeys(
                        _dn_to_name(str(g)) for g in groups if str(g).strip()
                    )),
                ))
            # Mock/flat servers may not return the paged control: no
            # cookie -> single pass. Real AD pages until cookie is empty.
            ctrl = (conn.result.get("controls") or {}).get(_PAGED_OID)
            cookie = ctrl["value"]["cookie"] if ctrl else None
            # zero-progress guard: a server that echoes a cookie with no
            # entries would otherwise loop forever
            if not cookie or page_len == 0:
                break
            pages += 1
            if pages > 1000:  # 500k entries at page size 500: pathological
                raise ValueError("ldap paging exceeded 1000 pages; aborting")
    finally:
        conn.unbind()
    return SyncSnapshot(accounts=accounts)


def _ldap_validate(config: dict, secret: str) -> None:
    base = _ldap_base(config)
    conn = None
    try:
        conn = _ldap_connect(config, secret, _timeout(config))
        conn.search(
            base, "(objectClass=*)", attributes=["objectClass"], size_limit=1,
        )
        if conn.result.get("result") != 0:
            raise ValueError(
                f"ldap base search failed: {conn.result.get('description')}"
            )
    except ValueError:
        raise
    except Exception as exc:  # noqa: BLE001 - surface any wire error as 400-able
        raise ValueError(f"ldap connect failed: {type(exc).__name__}: {exc}") from exc
    finally:
        if conn is not None:
            conn.unbind()


class LdapAdapter:
    async def fetch(self, config: dict, secret: str) -> SyncSnapshot:
        return await asyncio.to_thread(
            _ldap_fetch_sync, config, secret, _timeout(config)
        )

    def validate(self, config: dict, secret: str) -> None:
        _ldap_validate(config, secret)


# --------------------------------------------------------------- Entra

GRAPH = "https://graph.microsoft.com/v1.0"
_ENTRA_TOKEN_CACHE: dict[str, tuple[str, float]] = {}


def _entra_ids(config: dict) -> tuple[str, str]:
    tenant = (config.get("tenant_id") or "").strip()
    client_id = (config.get("client_id") or "").strip()
    if not tenant:
        raise ValueError("entra config missing tenant_id")
    if not client_id:
        raise ValueError("entra config missing client_id")
    return tenant, client_id


def _token_request(tenant: str, client_id: str, secret: str):
    return (
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": secret,
            "scope": "https://graph.microsoft.com/.default",
        },
    )


def _cache_token(payload: dict, key: str) -> str:
    token = payload.get("access_token") or ""
    if not token:
        raise ValueError("entra token response missing access_token")
    try:
        expires = float(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires = 3600.0
    _ENTRA_TOKEN_CACHE[key] = (token, time.monotonic() + max(expires - 60, 60))
    return token


def _entra_sync_client(timeout: float) -> httpx.Client:
    return httpx.Client(timeout=timeout)


def _entra_token_sync(config: dict, secret: str, timeout: float) -> str:
    tenant, client_id = _entra_ids(config)
    key = f"{tenant}:{client_id}"
    hit = _ENTRA_TOKEN_CACHE.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    url, data = _token_request(tenant, client_id, secret)
    with _entra_sync_client(timeout) as client:
        r = client.post(url, data=data)
    if r.status_code != 200:
        raise ValueError(
            f"entra token fetch failed: HTTP {r.status_code} {r.text[:200]}"
        )
    return _cache_token(r.json(), key)


async def _entra_token_async(
    config: dict, secret: str, client: httpx.AsyncClient
) -> str:
    tenant, client_id = _entra_ids(config)
    key = f"{tenant}:{client_id}"
    hit = _ENTRA_TOKEN_CACHE.get(key)
    if hit and hit[1] > time.monotonic():
        return hit[0]
    url, data = _token_request(tenant, client_id, secret)
    r = await client.post(url, data=data)
    if r.status_code != 200:
        raise ValueError(
            f"entra token fetch failed: HTTP {r.status_code} {r.text[:200]}"
        )
    return _cache_token(r.json(), key)


def _entra_async_client(timeout: float) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)


async def _entra_member_of(
    client: httpx.AsyncClient, headers: dict, user_id: str
) -> tuple[str, ...]:
    names: list[str] = []
    uid = quote(str(user_id), safe="")
    url: str | None = (
        f"{GRAPH}/users/{uid}/transitiveMemberOf/microsoft.graph.group"
        f"?$select=displayName&$top=999"
    )
    seen: set[str] = set()
    while url:
        if url in seen:
            break
        seen.add(url)
        r = await client.get(url, headers=headers)
        if r.status_code == 404:
            return tuple(names)  # user deleted mid-sync; keep what we have
        r.raise_for_status()
        payload = r.json()
        for group in payload.get("value") or []:
            name = (group.get("displayName") or "").strip()
            if name:
                names.append(name)
        url = payload.get("@odata.nextLink")
    return tuple(dict.fromkeys(names))


async def _entra_fetch(config: dict, secret: str, timeout: float) -> SyncSnapshot:
    async with _entra_async_client(timeout) as client:
        token = await _entra_token_async(config, secret, client)
        headers = {
            "Authorization": f"Bearer {token}",
            "ConsistencyLevel": "eventual",
        }
        accounts: list[AccountRecord] = []
        url: str | None = f"{GRAPH}/users?$select=id,userPrincipalName,mail&$top=999"
        seen: set[str] = set()
        while url:
            if url in seen:
                raise ValueError("entra pagination loop detected")
            seen.add(url)
            r = await client.get(url, headers=headers)
            r.raise_for_status()
            payload = r.json()
            for user in payload.get("value") or []:
                value = (
                    user.get("userPrincipalName")
                    or user.get("mail")
                    or user.get("id")
                    or ""
                ).strip()
                if not value:
                    continue
                ents = await _entra_member_of(client, headers, user.get("id") or value)
                accounts.append(AccountRecord(
                    value=value,
                    account_type="username",
                    entitlements=ents,
                ))
            url = payload.get("@odata.nextLink")
    return SyncSnapshot(accounts=accounts)


class EntraAdapter:
    async def fetch(self, config: dict, secret: str) -> SyncSnapshot:
        return await _entra_fetch(config, secret, _timeout(config))

    def validate(self, config: dict, secret: str) -> None:
        _entra_token_sync(config, secret, _timeout(config))


# ---------------------------------------------------------------- SQL

_SELECT_RE = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)


def _sql_query(config: dict) -> str:
    query = (config.get("query") or "").strip().rstrip(";").strip()
    if not _SELECT_RE.match(query):
        raise ValueError(
            "sql connector query must be a SELECT (or WITH ... SELECT) statement"
        )
    return query


def _sql_dsn(config: dict, secret: str) -> str:
    url = (config.get("url") or "").strip()
    if not url:
        raise ValueError("sql config missing url")
    if "$SECRET" in url:
        url = url.replace("$SECRET", secret)
    if url.startswith("postgresql+asyncpg"):
        url = url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)
    elif url.startswith("sqlite+aiosqlite"):
        url = url.replace("sqlite+aiosqlite", "sqlite", 1)
    return url


def _sql_engine(dsn: str, timeout: float):
    from sqlalchemy.pool import NullPool

    connect_args: dict = {}
    if dsn.startswith("sqlite"):
        connect_args["timeout"] = timeout
    elif dsn.startswith("postgresql"):
        connect_args["connect_timeout"] = max(int(timeout), 1)
    return create_engine(dsn, poolclass=NullPool, connect_args=connect_args)


def _sql_connect(dsn: str, timeout: float):
    """Connect + enforce READ ONLY on Postgres as the first statement of
    the implicit transaction (spec: SET TRANSACTION READ ONLY)."""
    engine = _sql_engine(dsn, timeout)
    conn = engine.connect()
    if dsn.startswith("postgresql"):
        conn.execute(text("SET TRANSACTION READ ONLY"))
    return engine, conn


def _row_records(rows) -> list[AccountRecord]:
    accounts: list[AccountRecord] = []
    for row in rows:
        value = str(row.get("account") or "").strip() if row.get("account") is not None else ""
        if not value:
            continue
        ent = row.get("entitlement")
        ent_name = str(ent).strip() if ent is not None else ""
        priv = row.get("privilege")
        priv_name = str(priv).strip().lower() if priv is not None else ""
        accounts.append(AccountRecord(
            value=value,
            account_type="username",
            privilege=priv_name or None,
            entitlements=(ent_name,) if ent_name else (),
        ))
    return accounts


def _sql_fetch_sync(config: dict, secret: str, timeout: float) -> SyncSnapshot:
    query = _sql_query(config)
    dsn = _sql_dsn(config, secret)
    engine, conn = _sql_connect(dsn, timeout)
    try:
        rows = conn.execute(text(query)).mappings().all()
    finally:
        conn.close()
        engine.dispose()
    return SyncSnapshot(accounts=_row_records(rows))


def _sql_validate(config: dict, secret: str) -> None:
    query = _sql_query(config)
    dsn = _sql_dsn(config, secret)
    engine, conn = _sql_connect(dsn, _timeout(config))
    try:
        cols = [str(c).lower() for c in conn.execute(
            text(f"SELECT * FROM ({query}) _iag_probe LIMIT 1")
        ).keys()]
    finally:
        conn.close()
        engine.dispose()
    if "account" not in cols:
        raise ValueError(
            "sql query must return an 'account' column "
            f"(got columns: {', '.join(cols) or 'none'})"
        )


class SqlAdapter:
    async def fetch(self, config: dict, secret: str) -> SyncSnapshot:
        return await asyncio.to_thread(
            _sql_fetch_sync, config, secret, _timeout(config)
        )

    def validate(self, config: dict, secret: str) -> None:
        _sql_validate(config, secret)


# ------------------------------------------------------------ Registry

_ADAPTERS: dict[str, object] = {
    "ldap": LdapAdapter(),
    "entra": EntraAdapter(),
    "sql": SqlAdapter(),
}


def get_adapter(source_type: str):
    """Adapter for a SourceType value. csv/xlsx raise ValueError: they
    are upload-only sources (manual sync must 400)."""
    try:
        return _ADAPTERS[source_type]
    except KeyError:
        raise ValueError(
            f"no connector adapter for source type {source_type!r}"
        ) from None
