"""Enforcement write-back arms (Feature 6 Phase D / spec Part 2).

Each arm translates the action's frozen snapshot (account_value,
entitlement_name, data_source_id, target) into directory-native
identifiers and performs ONE deliberate write through the source's
connector configuration:

- ldap: resolve user DN by account_attr search, group DN by name
  (cn= or ou= under the configured group base); member MODIFY_DELETE
  for remove_entitlement, attribute MODIFY_REPLACE for disable_account.
- entra: resolve user id by UPN, group id by displayName; DELETE
  member $ref (404 = already clean), PATCH accountEnabled=false.
- sql: admin-supplied remove_entitlement_sql / disable_account_sql
  with :account_value / :entitlement_name bind params, run through
  the source's sync engine EXCEPT read-write — the one deliberate
  write in the system.

Safety contract (spec "Idempotency & safety"): already-clean is a
SUCCESS without writing; resolution failure fails loudly, never
guesses or writes by approximate match; enforcement never mutates
the access mirror (next sync reflects reality).
"""
from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.core import connectors as _cx
from app.core.connectors import (
    GRAPH,
    _entra_token_async,
    _ldap_base,
    _sql_dsn,
    _sql_engine,
    _timeout,
)

REMOVE_ENTITLEMENT = "remove_entitlement"
DISABLE_ACCOUNT = "disable_account"


def _escape_filter(value: str) -> str:
    from ldap3.utils.conv import escape_filter_chars

    return escape_filter_chars(value)


def _odata_escape(value: str) -> str:
    return value.replace("'", "''")


# ---------------------------------------------------------------- LDAP


def _ldap_connect_write(config: dict, secret: str, timeout: float):
    """Like connectors._ldap_connect but writable: enforcement is the one
    deliberate directory write, so the sync adapter's read_only guard is
    deliberately not applied here. receive_timeout must stay int (pyasn1)."""
    from ldap3 import Connection, Server

    server = Server(config["url"], connect_timeout=timeout)
    return Connection(
        server,
        user=config.get("bind_dn") or None,
        password=secret,
        auto_bind=True,
        receive_timeout=int(timeout),
    )


def _ldap_find_user_dn(conn, config: dict, account_value: str) -> tuple[str, str]:
    """Exact account_attr match -> (user_dn, attr_value). Never approximate:
    zero or multiple hits fail."""
    base = _ldap_base(config)
    account_attr = config.get("account_attr") or "sAMAccountName"
    conn.search(
        base,
        f"({account_attr}={_escape_filter(account_value)})",
        attributes=[account_attr],
    )
    entries = conn.entries
    if not entries:
        raise RuntimeError(
            f"ldap user not found: ({account_attr}={account_value}) under {base}"
        )
    if len(entries) > 1:
        raise RuntimeError(
            f"ldap account ambiguous: {len(entries)} entries match "
            f"({account_attr}={account_value}); refusing to guess"
        )
    entry = entries[0]
    attrs = entry.entry_attributes_as_dict
    values = attrs.get(account_attr) or []
    resolved = str(values[0]).strip() if values else ""
    if resolved != account_value:
        raise RuntimeError(
            f"ldap identity mismatch: resolved {account_attr}={resolved!r} != "
            f"account_value {account_value!r}; aborting"
        )
    return entry.entry_dn, resolved


def _ldap_find_group_dn(conn, config: dict, entitlement_name: str) -> str:
    """Entitlement name -> group DN. Sync collapses the group DN's first
    RDN (cn= or ou=) to the name; enforcement re-expands it by searching
    the configured group base (default: base_dn)."""
    base = (config.get("group_base") or _ldap_base(config)).strip()
    name = _escape_filter(entitlement_name)
    conn.search(
        base, f"(|(cn={name})(ou={name}))", attributes=["objectClass"],
    )
    entries = conn.entries
    if not entries:
        raise RuntimeError(
            f"ldap group not found: no cn/ou == {entitlement_name!r} under {base}"
        )
    if len(entries) > 1:
        raise RuntimeError(
            f"ldap group ambiguous: {len(entries)} entries named "
            f"{entitlement_name!r} under {base}; refusing to guess"
        )
    return entries[0].entry_dn


def _ldap_group_members(conn, group_dn: str) -> list[str]:
    """Forward-link truth: the group entry's member values. Read from the
    group, not the user's memberOf back-link — back-links go stale after
    direct writes in some directories, and this is the exact list a
    MODIFY_DELETE would act on."""
    conn.search(group_dn, "(objectClass=*)", attributes=["member"])
    entries = conn.entries
    if not entries:
        return []
    vals = entries[0].entry_attributes_as_dict.get("member") or []
    return [str(v) for v in vals]


def _ldap_remove_entitlement(conn, config: dict, snapshot: dict) -> str:
    from ldap3 import MODIFY_DELETE

    entitlement_name = snapshot.get("entitlement_name")
    if not entitlement_name:
        raise RuntimeError(
            "no entitlement in snapshot; remove_entitlement cannot proceed"
        )
    user_dn, account_value = _ldap_find_user_dn(conn, config, snapshot["account_value"])
    group_dn = _ldap_find_group_dn(conn, config, entitlement_name)
    if user_dn not in _ldap_group_members(conn, group_dn):
        return (
            f"ldap remove_entitlement: already clean — {account_value} is not a "
            f"member of {entitlement_name}"
        )
    if not conn.modify(
        group_dn, {"member": [(MODIFY_DELETE, [user_dn])]}
    ):
        raise RuntimeError(
            f"ldap modify failed: {conn.result.get('description')}"
        )
    return (
        f"ldap remove_entitlement: removed {account_value} from "
        f"{entitlement_name} ({group_dn})"
    )


def _ldap_disable_account(conn, config: dict, snapshot: dict) -> str:
    from ldap3 import MODIFY_REPLACE

    disable_attr = (config.get("disable_attr") or "").strip()
    disable_value = str(config.get("disable_value", "")).strip()
    if not disable_attr or not disable_value:
        raise RuntimeError(
            "ldap disable_account needs disable_attr and disable_value in the "
            "source's connector config (see docs/admin-guide.md)"
        )
    user_dn, account_value = _ldap_find_user_dn(conn, config, snapshot["account_value"])
    conn.search(user_dn, "(objectClass=*)", attributes=[disable_attr])
    entries = conn.entries
    current = None
    if entries:
        vals = entries[0].entry_attributes_as_dict.get(disable_attr) or []
        current = str(vals[0]).strip() if vals else None
    if current == disable_value:
        return (
            f"ldap disable_account: already clean — {disable_attr} already "
            f"{disable_value} on {account_value}"
        )
    if not conn.modify(
        user_dn, {disable_attr: [(MODIFY_REPLACE, [disable_value])]}
    ):
        raise RuntimeError(
            f"ldap modify failed: {conn.result.get('description')}"
        )
    return (
        f"ldap disable_account: set {disable_attr}={disable_value} on "
        f"{account_value} ({user_dn})"
    )


def _ldap_enforce_sync(config: dict, secret: str, timeout: float,
                       snapshot: dict, target: str) -> str:
    conn = _ldap_connect_write(config, secret, timeout)
    try:
        if target == REMOVE_ENTITLEMENT:
            return _ldap_remove_entitlement(conn, config, snapshot)
        return _ldap_disable_account(conn, config, snapshot)
    finally:
        conn.unbind()


async def _enforce_ldap(config: dict, secret: str, snapshot: dict,
                        target: str) -> str:
    return await asyncio.to_thread(
        _ldap_enforce_sync, config, secret, _timeout(config), snapshot, target
    )


# --------------------------------------------------------------- Entra


def _entra_request(
    client, headers: dict, method: str, path: str,
    *, params: dict | None = None, json_body: dict | None = None,
):
    return client.request(
        method, f"{GRAPH}{path}", headers=headers,
        params=params, json=json_body,
    )


async def _entra_resolve_user_id(
    client, headers: dict, account_value: str
) -> str:
    from urllib.parse import quote

    r = await _entra_request(
        client, headers, "GET", "/users",
        params={"$filter": f"userPrincipalName eq '{_odata_escape(account_value)}'",
                "$select": "id,userPrincipalName"},
    )
    r.raise_for_status()
    matches = r.json().get("value") or []
    if not matches:
        raise RuntimeError(f"entra user not found: UPN {account_value!r}")
    if len(matches) > 1:
        raise RuntimeError(
            f"entra account ambiguous: {len(matches)} users with UPN "
            f"{account_value!r}; refusing to guess"
        )
    resolved = (matches[0].get("userPrincipalName") or "").strip()
    if resolved != account_value:
        raise RuntimeError(
            f"entra identity mismatch: resolved UPN {resolved!r} != "
            f"account_value {account_value!r}; aborting"
        )
    return str(matches[0].get("id") or quote(account_value, safe=""))


async def _entra_resolve_group_id(
    client, headers: dict, entitlement_name: str
) -> str:
    r = await _entra_request(
        client, headers, "GET", "/groups",
        params={"$filter": f"displayName eq '{_odata_escape(entitlement_name)}'",
                "$select": "id,displayName"},
    )
    r.raise_for_status()
    matches = r.json().get("value") or []
    if not matches:
        raise RuntimeError(f"entra group not found: {entitlement_name!r}")
    if len(matches) > 1:
        raise RuntimeError(
            f"entra group ambiguous: {len(matches)} groups named "
            f"{entitlement_name!r}; refusing to guess"
        )
    return str(matches[0]["id"])


async def _entra_remove_entitlement(
    client, headers: dict, snapshot: dict
) -> str:
    from urllib.parse import quote

    entitlement_name = snapshot.get("entitlement_name")
    if not entitlement_name:
        raise RuntimeError(
            "no entitlement in snapshot; remove_entitlement cannot proceed"
        )
    account_value = snapshot["account_value"]
    uid = quote(await _entra_resolve_user_id(client, headers, account_value), safe="")
    gid = quote(
        await _entra_resolve_group_id(client, headers, entitlement_name), safe=""
    )
    r = await _entra_request(
        client, headers, "DELETE",
        f"/groups/{gid}/members/{uid}/$ref",
    )
    if r.status_code == 404:
        return (
            f"entra remove_entitlement: already clean — {account_value} is not "
            f"a member of {entitlement_name}"
        )
    r.raise_for_status()
    return (
        f"entra remove_entitlement: removed {account_value} from "
        f"{entitlement_name} ({gid})"
    )


async def _entra_disable_account(
    client, headers: dict, snapshot: dict
) -> str:
    from urllib.parse import quote

    account_value = snapshot["account_value"]
    uid = quote(await _entra_resolve_user_id(client, headers, account_value), safe="")
    r = await _entra_request(
        client, headers, "GET", f"/users/{uid}", params={"$select": "accountEnabled"},
    )
    r.raise_for_status()
    if r.json().get("accountEnabled") is False:
        return (
            f"entra disable_account: already clean — {account_value} already "
            f"disabled"
        )
    r = await _entra_request(
        client, headers, "PATCH", f"/users/{uid}",
        json_body={"accountEnabled": False},
    )
    r.raise_for_status()
    return f"entra disable_account: accountEnabled=false on {account_value}"


async def _enforce_entra(config: dict, secret: str, snapshot: dict,
                         target: str) -> str:
    # Late-bind the client factory through the connectors module so a single
    # monkeypatch of connectors._entra_async_client covers fetch + enforcement.
    async with _cx._entra_async_client(_timeout(config)) as client:
        token = await _entra_token_async(config, secret, client)
        headers = {"Authorization": f"Bearer {token}"}
        if target == REMOVE_ENTITLEMENT:
            return await _entra_remove_entitlement(client, headers, snapshot)
        return await _entra_disable_account(client, headers, snapshot)


# ----------------------------------------------------------------- SQL


def _sql_statement(config: dict, target: str) -> str:
    key = f"{target}_sql"
    stmt = (config.get(key) or "").strip().rstrip(";").strip()
    if not stmt:
        raise RuntimeError(
            f"sql source has no {key} configured; enforcement requires an "
            "admin-supplied statement (see docs/admin-guide.md)"
        )
    return stmt


def _sql_bind_params(snapshot: dict) -> dict:
    return {
        "account_value": snapshot["account_value"],
        "entitlement_name": snapshot.get("entitlement_name"),
    }


def _sql_enforce_sync(config: dict, secret: str, timeout: float,
                      snapshot: dict, target: str) -> str:
    stmt = _sql_statement(config, target)
    dsn = _sql_dsn(config, secret)
    engine = _sql_engine(dsn, timeout)
    try:
        with engine.connect() as conn:
            if dsn.startswith("postgresql"):
                # The read arm pins READ ONLY; enforcement is the one
                # deliberate write — pin the opposite, loudly.
                conn.execute(text("SET TRANSACTION READ WRITE"))
            result = conn.execute(text(stmt), _sql_bind_params(snapshot))
            rowcount = getattr(result, "rowcount", -1)
            conn.commit()
    finally:
        engine.dispose()
    return (
        f"sql {target}: statement executed, {rowcount} row(s) affected "
        f"on {snapshot['account_value']}"
    )


async def _enforce_sql(config: dict, secret: str, snapshot: dict,
                       target: str) -> str:
    return await asyncio.to_thread(
        _sql_enforce_sync, config, secret, _timeout(config), snapshot, target
    )


# ------------------------------------------------------------- Dispatch

_ARMS = {
    "ldap": _enforce_ldap,
    "entra": _enforce_entra,
    "sql": _enforce_sql,
}


async def enforce_against_source(source_type: str, config: dict, secret: str,
                                 snapshot: dict, target: str) -> str:
    """Dispatch one enforcement write. csv/xlsx and unknown types have no
    write-back arm — that is a config error, not a fall-through."""
    arm = _ARMS.get(source_type)
    if arm is None:
        raise RuntimeError(
            f"source type {source_type!r} has no enforcement write-back; "
            "enforce rules need an ldap, entra, or sql connector source"
        )
    if target not in (REMOVE_ENTITLEMENT, DISABLE_ACCOUNT):
        raise RuntimeError(f"unknown enforce target {target!r}")
    return await arm(config, secret, snapshot, target)
