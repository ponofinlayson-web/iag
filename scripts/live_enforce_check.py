"""Live enforcement write-back proof (Feature 6 Phase E) against a real
writable directory + real Postgres, through the real API surface.

Spec named glauth for this proof; the live probe found glauth CANNOT
receive writes (config backend: every MODIFY returns result 50
insufficientAccessRights; groups carry no forward-link member attr at
all). The proof runs against the writable OpenLDAP in the same compose
profile "connectors" instead (iag-openldap, deploy/enforce.ldif). Entra
has no local tenant: that arm stays MockTransport-proven (tests); this
script proves ldap + sql write-back live.

Legs:
 1. bootstraps OpenLDAP for enforcement (memberOf overlay repointed to
    groupOfNames/member when needed + member re-touch so back-links
    compute — osixia default overlay targets uniqueMember; no config
    volume is mounted, so bootstrap is idempotent, per-run).
 2. ldap remove_entitlement E2E: source -> connector -> sync (memberOf
    truth) -> psql-bind account.entitlement_id (E2E test house style;
    connector sync leaves it null by design and no API sets it) ->
    campaign -> revoke -> enforce rule -> worker removes member from
    group (assert via direct directory read) -> re-sync -> account row
    intact.
 3. already-clean second run: same flow -> completes without writing.
 4. disable_account leg: attr flip on the user entry (MODIFY_REPLACE),
    then its already-clean second run.
 5. sql write-back: planted table in the stack Postgres, admin
    remove_entitlement_sql statement with bind params, row actually
    deleted, asserted via psql.
 6. audit chain valid at end.

Prereqs: docker compose --profile connectors up -d iag-openldap;
IAG_BOOTSTRAP_ADMIN_PASSWORD + IAG_APP_DB_PASSWORD in env (or sourced
.env); stack rebuilt (enforcement.py in the image).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

BASE = os.environ.get("IAG_BASE_URL", "http://localhost:8090")
PW = os.environ.get("IAG_BOOTSTRAP_ADMIN_PASSWORD", "")
APP_DB_PW = os.environ.get("IAG_APP_DB_PASSWORD", "")

LDAP_HOST = "ldap://iag-openldap:389"
ROOT_DN = "cn=admin,dc=iagldap,dc=local"
ROOT_PW = "iag-ldap-proof-admin"
BASE_DN = "dc=iagldap,dc=local"
PEOPLE = "ou=people,dc=iagldap,dc=local"
GROUPS = "ou=groups,dc=iagldap,dc=local"
BOB_DN = "uid=lp-bob,ou=people,dc=iagldap,dc=local"
ADMINS_DN = "cn=Proof-Admins,ou=groups,dc=iagldap,dc=local"
TAG = os.environ.get("IAG_ENFORCE_TAG", "") or os.urandom(3).hex()
SRC_LDAP = f"__live_enforce_ldap_{TAG}__"
SRC_SQL = f"__live_enforce_sql_{TAG}__"
RULE_NAME = f"live-enforce-{TAG}"
DISABLE_RULE = RULE_NAME + "-dis"
DISABLE_ATTR = "description"
DISABLE_VAL = "disabled-by-iag-enforce"


def log(msg):
    print(msg, flush=True)


def call(method, path, body=None, cookie=None):
    req = urllib.request.Request(BASE + path, method=method)
    if cookie:
        req.add_header("Cookie", cookie)
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, data) as r:
            sc = r.headers.get("Set-Cookie", "")
            return r.status, json.loads(r.read()), sc
    except urllib.error.HTTPError as e:
        raw = e.read() or b"{}"
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"detail": raw.decode("utf-8", "replace")[:200]}
        return e.code, parsed, ""


def psql(sql):
    r = subprocess.run(
        ["docker", "exec", "iag-db", "psql", "-U", "iag_migrate", "-d",
         "iag", "-tAc", sql],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr}")
    return r.stdout.strip()


def docker_exec(container, argv):
    r = subprocess.run(["docker", "exec", container] + argv,
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"docker exec {container} failed: {r.stderr or r.stdout}")
    return r.stdout


def ldap_py(code):
    """Run a python snippet against the directory from inside an app
    container (ldap3 lives in the image venv; the host has none).
    Windows docker cp needs a real file - /dev/stdin is not a path."""
    script = "from ldap3 import Server, Connection\n" + code
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(script)
        local = f.name
    path = f"/tmp/{os.path.basename(local)}"
    try:
        subprocess.run(["docker", "cp", local, f"iag-app-1:{path}"], check=True)
        return docker_exec("iag-app-1", ["/app/.venv/bin/python", path])
    finally:
        # nobody-user exec may lack unlink rights; leave-behind is
        # harmless (/tmp scratch), so cleanup is best-effort
        subprocess.run(["docker", "exec", "iag-app-1", "rm", "-f", path],
                       capture_output=True)
        os.unlink(local)


# ---------------------------------------------------------- preconditions
try:
    docker_exec("iag-openldap", ["ldapwhoami", "-Q", "-Y", "EXTERNAL", "-H", "ldapi://"])
except RuntimeError as e:
    sys.exit(f"iag-openldap not reachable: {e}\n"
             "docker compose --profile connectors up -d iag-openldap")

# memberOf overlay must target groupOfNames/member (osixia default is
# uniqueMember); idempotent: only rewrite when actually different.
overlay = docker_exec("iag-openldap", [
    "ldapsearch", "-Q", "-Y", "EXTERNAL", "-H", "ldapi://", "-b",
    "olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config", "-s", "base",
    "-LLL", "olcMemberOfGroupOC", "olcMemberOfMemberAD",
])
if "groupOfNames" not in overlay or "memberAD: member" not in overlay:
    fix = (
        "dn: olcOverlay={0}memberof,olcDatabase={1}mdb,cn=config\n"
        "changetype: modify\n"
        "replace: olcMemberOfGroupOC\nolcMemberOfGroupOC: groupOfNames\n"
        "-\n"
        "replace: olcMemberOfMemberAD\nolcMemberOfMemberAD: member\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".ldif", delete=False) as f:
        f.write(fix)
        local = f.name
    subprocess.run(["docker", "cp", local, "iag-openldap:/tmp/_fix.ldif"], check=True)
    os.unlink(local)
    docker_exec("iag-openldap",
                ["ldapmodify", "-Q", "-Y", "EXTERNAL", "-H", "ldapi://",
                 "-f", "/tmp/_fix.ldif"])
    log("memberOf overlay repointed to groupOfNames/member")

# seeded members predate any overlay state -> re-touch so back-links
# compute. Recover from any state: first ADD any missing expected
# member (an earlier interrupted run can leave the group drained),
# then interleaved delete+add per member - groupOfNames requires at
# least one member, so never touch below that.
retouch = """
c = Connection(Server('LDAPURL', connect_timeout=5), user='ROOTDN', password='ROOTPW',
               auto_bind=True, receive_timeout=5)
from ldap3 import MODIFY_DELETE, MODIFY_ADD
expected = ['uid=lp-alice,ou=people,dc=iagldap,dc=local',
            'uid=lp-bob,ou=people,dc=iagldap,dc=local',
            'uid=lp-carol,ou=people,dc=iagldap,dc=local']
c.search('GROUPS', '(cn=Proof-Admins)', attributes=['member'])
current = [str(v) for v in c.entries[0].entry_attributes_as_dict.get('member', [])]
for dn in expected:
    if dn not in current:
        assert c.modify('ADMINS', {'member': [(MODIFY_ADD, [dn])]}), dn
for dn in expected:
    assert c.modify('ADMINS', {'member': [(MODIFY_DELETE, [dn])]}), dn
    assert c.modify('ADMINS', {'member': [(MODIFY_ADD, [dn])]}), dn
c.search('LDAPBASE', '(uid=lp-bob)', attributes=['memberOf'])
print('memberOf:', sorted(str(v) for v in
      c.entries[0].entry_attributes_as_dict.get('memberOf', [])))
c.unbind()
""".replace("LDAPURL", LDAP_HOST).replace("ROOTDN", ROOT_DN).replace("ROOTPW", ROOT_PW) \
   .replace("GROUPS", GROUPS).replace("ADMINS", ADMINS_DN).replace("LDAPBASE", BASE_DN)
out = ldap_py(retouch)
log("directory bootstrapped: " + out.strip())
assert "Proof-Admins" in out, f"memberOf back-link not computing: {out}"

# reset disable attr from any prior run so the disable leg asserts a
# real transition, not "already clean"
reset_disable = """
c = Connection(Server('LDAPURL', connect_timeout=5), user='ROOTDN', password='ROOTPW',
               auto_bind=True, receive_timeout=5)
from ldap3 import MODIFY_REPLACE
c.search('PEOPLE', '(uid=lp-bob)', attributes=['DISABLEATTR'])
vals = [str(v) for v in
        c.entries[0].entry_attributes_as_dict.get('DISABLEATTR', [])]
if vals:
    from ldap3 import MODIFY_DELETE
    assert c.modify('BOBDN', {'DISABLEATTR': [(MODIFY_DELETE, vals)]})
print('desc after reset:', vals)
c.unbind()
""".replace("LDAPURL", LDAP_HOST).replace("ROOTDN", ROOT_DN).replace("ROOTPW", ROOT_PW) \
   .replace("PEOPLE", PEOPLE).replace("DISABLEATTR", DISABLE_ATTR).replace("BOBDN", BOB_DN)
out = ldap_py(reset_disable)
log("disable attr reset: " + out.strip())

# ------------------------------------------------------------- API login
log(f"== live enforcement proof (tag {TAG}) ==")
st, body, cookie = call("POST", "/api/auth/login", {"username": "admin", "password": PW})
assert st == 200, f"login {st}: {body}"
cookie = cookie.split(";")[0] if cookie else ""
assert cookie, "no session cookie"

SID_LDAP = 0
SID_SQL = 0


def wait_run(run_id, timeout=90):
    deadline = time.time() + timeout
    while time.time() < deadline:
        st, detail, _ = call("GET", f"/api/syncs/{run_id}", cookie=cookie)
        assert st == 200, f"sync detail {st}: {detail}"
        if detail["status"] in ("done", "failed", "cancelled"):
            return detail
        time.sleep(2)
    raise AssertionError(f"sync run {run_id} did not finish")


def sync_source(sid):
    st, body, _ = call("POST", f"/api/sources/{sid}/sync", cookie=cookie)
    assert st == 200, f"sync trigger {st}: {body}"
    detail = wait_run(body["run_id"])
    assert detail["status"] == "done", f"sync failed: {detail}"
    return detail


def enforce_cycle(campaign_name, rule_name, expect_result):
    """Campaign -> revoke bob only -> approve if gated -> completed action."""
    st, _, _ = call("POST", "/api/campaigns", cookie=cookie, body={
        "name": campaign_name, "scope": {"data_source_ids": [SID_LDAP]}})
    assert st in (200, 409), f"campaign create {st}"
    camps = call("GET", "/api/campaigns", cookie=cookie)[1]["items"]
    cid = next(c for c in camps if c["name"] == campaign_name)["id"]
    call("POST", f"/api/campaigns/{cid}/stage", cookie=cookie)
    st, body, _ = call("POST", f"/api/campaigns/{cid}/start", cookie=cookie)
    assert st in (200, 409), f"start {st}: {body}"
    for _ in range(10):
        reviews = call("GET", "/api/reviews/queue", cookie=cookie)[1]["items"]
        if reviews:
            break
        time.sleep(1)
    assert reviews, "no reviews created"
    bob_rv = next(r for r in reviews if r["account_value"] == "lp-bob")
    st, body, _ = call("POST", f"/api/reviews/{bob_rv['id']}/submit", cookie=cookie,
                       body={"decision": "revoke", "comments": "live enforce proof"})
    assert st == 200, f"revoke submit {st}: {body}"
    # D6: enforce defaults approval ON. These rules opted out for speed;
    # the gate itself is pinned by the test suite.
    deadline = time.time() + 30
    action = None
    while time.time() < deadline and action is None:
        actions = call("GET", "/api/remediation/actions?limit=100",
                       cookie=cookie)[1]["items"]
        for a in actions:
            if a["rule_name"] == rule_name \
                    and a["snapshot"].get("account_value") == "lp-bob" \
                    and a["snapshot"].get("campaign_id") == cid:
                action = a
                break
        if action is None:
            time.sleep(1)
    assert action, "enforce action not created"
    if action["status"] == "pending_approval":
        st, body, _ = call("PUT",
                           f"/api/remediation/actions/{action['id']}",
                           cookie=cookie, body={"op": "approve"})
        assert st == 200, f"approve {st}: {body}"
    deadline = time.time() + 60
    while time.time() < deadline:
        actions = call("GET", "/api/remediation/actions?limit=100",
                       cookie=cookie)[1]["items"]
        action = next(a for a in actions if a["id"] == action["id"])
        if action["status"] in ("completed", "failed"):
            break
        time.sleep(2)
    assert action["status"] == "completed", f"action not completed: {action}"
    assert expect_result in (action["result"] or ""), \
        f"result mismatch: {action['result']!r} lacks {expect_result!r}"
    return action


# cleanup prior-run artifacts (psql: API delete has no cascade)
psql("DELETE FROM remediation_actions WHERE rule_id IN "
     "(SELECT id FROM remediation_rules WHERE name LIKE 'live-enforce-%')")
psql("DELETE FROM remediation_rules WHERE name LIKE 'live-enforce-%'")
psql("DELETE FROM reviews WHERE campaign_id IN "
     "(SELECT id FROM campaigns WHERE name LIKE '\\_\\_live\\_enforce\\_%' ESCAPE '\\')")
psql("DELETE FROM campaigns WHERE name LIKE '\\_\\_live\\_enforce\\_%' ESCAPE '\\'")
psql("DELETE FROM remediation_actions WHERE account_id IN "
     "(SELECT id FROM accounts WHERE data_source_id IN "
     "(SELECT id FROM data_sources WHERE name LIKE '\\_\\_live\\_enforce\\_%' ESCAPE '\\'))")
for tbl in ("accounts", "sync_runs", "entitlements"):
    psql(f"DELETE FROM {tbl} WHERE data_source_id IN "
         "(SELECT id FROM data_sources WHERE name LIKE '\\_\\_live\\_enforce\\_%' ESCAPE '\\')")
psql("DELETE FROM data_sources WHERE name LIKE '\\_\\_live\\_enforce\\_%' ESCAPE '\\'")


# ------------------------------------------------- 1. source + connector
# owner_employee_id E-ADMIN = bootstrap admin identity; source_owner
# review mode skips sources with no owner (campaign start "skipped")
st, body, _ = call("POST", "/api/sources", cookie=cookie, body={
    "name": SRC_LDAP, "source_type": "ldap", "owner_employee_id": "E-ADMIN"})
assert st == 200, f"create ldap source {st}: {body}"
SID_LDAP = body["id"]
log(f"ldap source #{SID_LDAP} created")

st, body, _ = call("PUT", f"/api/sources/{SID_LDAP}/connector", cookie=cookie, body={
    "config": {
        "url": LDAP_HOST, "base_dn": BASE_DN, "bind_dn": ROOT_DN,
        "filter": "(objectClass=inetOrgPerson)", "account_attr": "uid",
        "group_base": GROUPS,
        "disable_attr": DISABLE_ATTR, "disable_value": DISABLE_VAL,
    },
    "secret": ROOT_PW})
assert st == 200, f"connector PUT {st}: {body}"
log("connector configured + validated (live bind)")


# -------------------------------------------------------------- 2. sync
detail = sync_source(SID_LDAP)
log(f"sync done: {json.dumps(detail['stats'])}")
accts = call("GET", f"/api/sources/{SID_LDAP}/accounts?page_size=50",
             cookie=cookie)[1]["items"]
vals = {a["account_value"] for a in accts}
assert {"lp-alice", "lp-bob"} <= vals, f"accounts missing: {sorted(vals)}"
bob_id = next(a["id"] for a in accts if a["account_value"] == "lp-bob")
log(f"accounts verified: {sorted(vals)}")

ents = call("GET", f"/api/entitlements?source_id={SID_LDAP}&page_size=50",
            cookie=cookie)[1]["items"]
ent_names = {e["name"] for e in ents}
assert "Proof-Admins" in ent_names, f"Proof-Admins missing: {sorted(ent_names)}"
log(f"entitlement catalog: {sorted(ent_names)}")

# bind entitlement grain (house style: E2E tests psql-bind it; sync
# leaves Account.entitlement_id null by design for connector sources)
admin_ent_id = psql(f"SELECT id FROM entitlements WHERE data_source_id={SID_LDAP} "
                    "AND name='Proof-Admins'")
psql(f"UPDATE accounts SET entitlement_id={admin_ent_id} WHERE id={bob_id}")
log("bob bound to Proof-Admins (entitlement grain)")


# ------------------------------------------- 3. remove_entitlement leg
st, body, _ = call("POST", "/api/remediation/rules", cookie=cookie, body={
    "name": RULE_NAME, "action": "enforce", "target": "remove_entitlement",
    "data_source_id": SID_LDAP, "entitlement_pattern": "^Proof-Admins$",
    "require_approval": False,
})
assert st in (200, 201), f"rule create {st}: {body}"

action = enforce_cycle(f"__live_enforce_rm_{TAG}", RULE_NAME,
                       "ldap remove_entitlement: removed lp-bob from Proof-Admins")
log(f"remove_entitlement delivered: {(action['result'] or '')[:90]}")

# directory truth: bob gone, alice still member
check = ldap_py("""
c = Connection(Server('LDAPURL', connect_timeout=5), user='ROOTDN', password='ROOTPW',
               auto_bind=True, receive_timeout=5)
c.search('ADMINS', '(objectClass=*)', attributes=['member'])
print('members:', sorted(str(v) for v in
      c.entries[0].entry_attributes_as_dict.get('member', [])))
c.unbind()
""".replace("LDAPURL", LDAP_HOST).replace("ROOTDN", ROOT_DN).replace("ROOTPW", ROOT_PW)
   .replace("ADMINS", ADMINS_DN))
assert "lp-bob" not in check, f"bob still member: {check}"
assert "lp-alice" in check, f"alice should still be member: {check}"
log("directory truth: bob removed, alice intact [V]")

# re-sync: account row intact (mirror never deletes rows)
detail = sync_source(SID_LDAP)
accts = call("GET", f"/api/sources/{SID_LDAP}/accounts?page_size=50",
             cookie=cookie)[1]["items"]
bob = next(a for a in accts if a["account_value"] == "lp-bob")
assert bob["id"] == bob_id, "account row replaced (must be same row)"
log("re-sync: bob account row intact [V]")


# ---------------------------------------- 4. already-clean second run
action2 = enforce_cycle(f"__live_enforce_rm2_{TAG}", RULE_NAME, "already clean")
log(f"already-clean idempotent second run: {(action2['result'] or '')[:90]}")


# ------------------------------------------------- 5. disable_account leg
st, body, _ = call("POST", "/api/remediation/rules", cookie=cookie, body={
    "name": DISABLE_RULE, "action": "enforce", "target": "disable_account",
    "data_source_id": SID_LDAP, "require_approval": False,
})
assert st in (200, 201), f"disable rule create {st}: {body}"

action3 = enforce_cycle(f"__live_enforce_dis_{TAG}", DISABLE_RULE,
                        f"ldap disable_account: set {DISABLE_ATTR}={DISABLE_VAL}")
log(f"disable_account delivered: {(action3['result'] or '')[:90]}")

check = ldap_py("""
c = Connection(Server('LDAPURL', connect_timeout=5), user='ROOTDN', password='ROOTPW',
               auto_bind=True, receive_timeout=5)
c.search('PEOPLE', '(uid=lp-bob)', attributes=['DISABLEATTR'])
print('desc:', [str(v) for v in
      c.entries[0].entry_attributes_as_dict.get('DISABLEATTR', [])])
c.unbind()
""".replace("LDAPURL", LDAP_HOST).replace("ROOTDN", ROOT_DN).replace("ROOTPW", ROOT_PW)
   .replace("PEOPLE", PEOPLE).replace("DISABLEATTR", DISABLE_ATTR))
assert DISABLE_VAL in check, f"disable attr not set: {check}"
log(f"directory truth: {DISABLE_ATTR}={DISABLE_VAL} on bob [V]")

action4 = enforce_cycle(f"__live_enforce_dis2_{TAG}", DISABLE_RULE, "already clean")
log(f"disable already-clean second run: {(action4['result'] or '')[:90]}")


# ----------------------------------------------------- 6. sql write-back
log("== sql write-back leg (stack Postgres, admin statements) ==")
psql("DROP TABLE IF EXISTS live_enforce_demo")
psql("CREATE TABLE live_enforce_demo (account TEXT, entitlement TEXT, privilege TEXT); "
     "INSERT INTO live_enforce_demo VALUES "
     "('lp-bob','Proof-Admins','low'),('lp-alice','Proof-Admins','low')")
st, body, _ = call("POST", "/api/sources", cookie=cookie, body={
    "name": SRC_SQL, "source_type": "sql", "owner_employee_id": "E-ADMIN"})
assert st == 200, f"create sql source {st}: {body}"
SID_SQL = body["id"]

st, body, _ = call("PUT", f"/api/sources/{SID_SQL}/connector", cookie=cookie, body={
    "config": {
        "url": f"postgresql+psycopg2://iag_app:$SECRET@iag-db:5432/iag",
        "query": "SELECT account, entitlement, privilege FROM live_enforce_demo",
        "remove_entitlement_sql":
            "DELETE FROM live_enforce_demo WHERE account = :account_value "
            "AND entitlement = :entitlement_name",
    },
    "secret": APP_DB_PW})
assert st == 200, f"sql connector PUT {st}: {body}"
log("sql source + admin remove_entitlement_sql configured")

# the ldap rule is scoped to SID_LDAP; the sql leg needs its own rule
SQL_RULE = RULE_NAME + "-sql"
st, body, _ = call("POST", "/api/remediation/rules", cookie=cookie, body={
    "name": SQL_RULE, "action": "enforce", "target": "remove_entitlement",
    "data_source_id": SID_SQL, "require_approval": False,
})
assert st in (200, 201), f"sql rule create {st}: {body}"

detail = sync_source(SID_SQL)
log(f"sql sync done: {json.dumps(detail['stats'])}")

# bind entitlement grain BEFORE the revoke: the snapshot freezes
# entitlement_name at trigger (submit) time from account.entitlement_id
ent_id = psql(f"SELECT id FROM entitlements WHERE data_source_id={SID_SQL} "
              "AND name='Proof-Admins'")
bob_sql_id = psql(f"SELECT id FROM accounts WHERE data_source_id={SID_SQL} "
                  "AND account_value='lp-bob'")
psql(f"UPDATE accounts SET entitlement_id={ent_id} WHERE id={bob_sql_id}")

st, _, _ = call("POST", "/api/campaigns", cookie=cookie, body={
    "name": f"__live_enforce_sql_{TAG}",
    "scope": {"data_source_ids": [SID_SQL]}})
assert st in (200, 409), f"campaign {st}"
camps = call("GET", "/api/campaigns", cookie=cookie)[1]["items"]
cid = next(c for c in camps if c["name"] == f"__live_enforce_sql_{TAG}")["id"]
call("POST", f"/api/campaigns/{cid}/stage", cookie=cookie)
st, body, _ = call("POST", f"/api/campaigns/{cid}/start", cookie=cookie)
assert st in (200, 409), f"start {st}"
for _ in range(10):
    reviews = call("GET", "/api/reviews/queue", cookie=cookie)[1]["items"]
    if reviews:
        break
    time.sleep(1)
bob_sql = next(r for r in reviews if r["account_value"] == "lp-bob")
st, body, _ = call("POST", f"/api/reviews/{bob_sql['id']}/submit", cookie=cookie,
                   body={"decision": "revoke", "comments": "sql enforce"})
assert st == 200, f"sql revoke {st}: {body}"

deadline = time.time() + 60
action5 = None
while time.time() < deadline:
    actions = call("GET", "/api/remediation/actions?limit=100",
                   cookie=cookie)[1]["items"]
    mine = [a for a in actions if a["rule_name"] == SQL_RULE
            and a["snapshot"].get("account_value") == "lp-bob"
            and a["snapshot"].get("data_source_id") == SID_SQL]
    if mine and mine[-1]["status"] in ("completed", "failed"):
        action5 = mine[-1]
        break
    time.sleep(2)
assert action5, "sql enforce action never delivered"
assert action5["status"] == "completed", f"sql action failed: {action5}"
assert "sql remove_entitlement" in (action5["result"] or ""), action5
log(f"sql write-back delivered: {(action5['result'] or '')[:90]}")

n = psql("SELECT count(*) FROM live_enforce_demo WHERE account='lp-bob'")
assert n == "0", f"bob row still present: {n}"
n_alice = psql("SELECT count(*) FROM live_enforce_demo WHERE account='lp-alice'")
assert n_alice == "1", f"alice row lost: {n_alice}"
log("planted-table truth: bob row deleted, alice row intact [V]")

# ------------------------------------------------------ chain + cleanup
st, body, _ = call("GET", "/api/audit/verify", cookie=cookie)
assert st == 200 and body["valid"], f"chain broken: {body}"
log(f"audit chain valid, {body['entries']} entries")

psql("DROP TABLE IF EXISTS live_enforce_demo")
log("demo table dropped")
print("LIVE ENFORCE CHECK PASS")
