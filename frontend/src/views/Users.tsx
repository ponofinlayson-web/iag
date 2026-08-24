import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Role, UserRow } from "../api/client";
import { useAuth } from "../auth";
import { Badge, Card, Empty, errMsg, Modal, Typeahead, type TypeaheadItem } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";

const ROLES: Role[] = ["system_admin", "certification_admin", "reviewer", "auditor", "report_viewer"];

function toUtc(s: string): Date {
  // Backend dates are naive-UTC isoformat; comparisons must not read them as local.
  return new Date(s.endsWith("Z") ? s : s + "Z");
}

function roleTone(role: string): "accent" | "info" | "warn" | "neutral" {
  switch (role) {
    case "system_admin":
      return "accent";
    case "certification_admin":
      return "info";
    case "auditor":
      return "warn";
    default:
      return "neutral";
  }
}

function generatePassword(): string {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789";
  const bytes = new Uint8Array(14);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}

function userStatus(u: UserRow): { label: string; tone: "ok" | "bad" | "warn" } {
  if (u.locked_until && toUtc(u.locked_until) > new Date()) return { label: "locked", tone: "bad" };
  return u.is_active ? { label: "active", tone: "ok" } : { label: "disabled", tone: "bad" };
}

function isLocked(u: UserRow): boolean {
  return !!u.locked_until && toUtc(u.locked_until) > new Date();
}

function fullName(u: UserRow): string {
  return [u.first_name, u.last_name].filter(Boolean).join(" ") || "—";
}

export default function Users() {
  const { me } = useAuth();
  const [rows, setRows] = useState<UserRow[] | null>(null);
  const [error, setError] = useState("");

  // add-user modal state
  const [adding, setAdding] = useState(false);
  const [identity, setIdentity] = useState<TypeaheadItem | null>(null);
  const [newRole, setNewRole] = useState<Role>("reviewer");
  const [newPassword, setNewPassword] = useState("");
  const [busy, setBusy] = useState(false);

  // reveal-once modal (create + reset share it)
  const [reveal, setReveal] = useState<{ username: string; password: string } | null>(null);
  const [copied, setCopied] = useState(false);

  // per-row action modals
  const [roleTarget, setRoleTarget] = useState<UserRow | null>(null);
  const [roleValue, setRoleValue] = useState<Role>("reviewer");
  const [resetTarget, setResetTarget] = useState<UserRow | null>(null);
  const [resetPassword, setResetPassword] = useState("");

  function load() {
    api.users
      .list()
      .then((r) => setRows(r.items))
      .catch((e) => setError(errMsg(e)));
  }

  useEffect(load, []);

  function lookupIdentities(q: string): Promise<TypeaheadItem[]> {
    return api.identities
      .list({ q, page_size: 8 })
      .then((r) =>
        r.items.map((i) => ({
          id: i.id,
          label: i.username ?? i.employee_id,
          sub: [i.first_name, i.last_name].filter(Boolean).join(" ") || i.employee_id,
        })),
      );
  }

  function createUser() {
    if (!identity) return;
    setError("");
    setBusy(true);
    api.users
      .create({ identity_id: identity.id, role: newRole, password: newPassword })
      .then((u) => {
        setReveal({ username: u.username ?? "", password: newPassword });
        setCopied(false);
        setAdding(false);
        setIdentity(null);
        setNewPassword("");
        load();
      })
      .catch((e) => setError(errMsg(e)))
      .finally(() => setBusy(false));
  }

  function submitRole() {
    if (!roleTarget) return;
    setError("");
    const id = roleTarget.id;
    api.users
      .setRole(id, roleValue)
      .then(() => {
        setRoleTarget(null);
        load();
      })
      .catch((e) => setError(errMsg(e)));
  }

  function submitReset() {
    if (!resetTarget) return;
    setError("");
    const target = resetTarget;
    api.users
      .resetPassword(target.id, resetPassword)
      .then(() => {
        setReveal({ username: target.username ?? "", password: resetPassword });
        setCopied(false);
        setResetTarget(null);
        setResetPassword("");
        load();
      })
      .catch((e) => setError(errMsg(e)));
  }

  function setStatus(id: number, is_active: boolean) {
    setError("");
    api.users
      .setStatus(id, is_active)
      .then(load)
      .catch((e) => setError(errMsg(e)));
  }

  function unlock(id: number) {
    setError("");
    api.users
      .unlock(id)
      .then(load)
      .catch((e) => setError(errMsg(e)));
  }

  function copyPassword() {
    if (!reveal) return;
    navigator.clipboard
      .writeText(reveal.password)
      .then(() => setCopied(true))
      .catch(() => setError("Clipboard unavailable - copy manually"));
  }

  const columns: Column<UserRow>[] = [
    { key: "username", label: "Username", pinned: true, filter: "text" },
    { key: "name", label: "Name", value: (u) => fullName(u), filter: "text" },
    { key: "department", label: "Department", value: (u) => u.department ?? "", filter: "select" },
    {
      key: "role",
      label: "Role",
      filter: "select",
      render: (u) => <Badge tone={roleTone(u.role)}>{u.role}</Badge>,
    },
    {
      key: "status",
      label: "Status",
      filter: "select",
      value: (u) => userStatus(u).label,
      render: (u) => {
        const st = userStatus(u);
        return <Badge tone={st.tone}>{st.label}</Badge>;
      },
    },
    {
      key: "must_change_password",
      label: "Must change",
      value: (u) => (u.must_change_password ? "yes" : "no"),
      render: (u) =>
        u.must_change_password ? <Badge tone="warn">must change</Badge> : <span className="muted">—</span>,
    },
    { key: "failed_attempts", label: "Failures", value: (u) => u.failed_attempts },
    {
      key: "last_login",
      label: "Last login",
      value: (u) => u.last_login ?? "",
      render: (u) => (u.last_login ? toUtc(u.last_login).toLocaleString() : <span className="muted">never</span>),
    },
    {
      key: "actions",
      label: "Actions",
      sortable: false,
      render: (u) => (
        <span className="row">
          <button
            className="secondary"
            disabled={u.id === me?.id}
            title={u.id === me?.id ? "You cannot change your own role" : "Change role"}
            onClick={() => {
              setRoleTarget(u);
              setRoleValue(u.role);
            }}
          >
            Role
          </button>
          {isLocked(u) && (
            <button className="secondary" onClick={() => unlock(u.id)}>
              Unlock
            </button>
          )}
          <button
            className="secondary"
            disabled={u.id === me?.id && u.is_active}
            title={u.id === me?.id ? "You cannot deactivate your own account" : undefined}
            onClick={() => setStatus(u.id, !u.is_active)}
          >
            {u.is_active ? "Deactivate" : "Reactivate"}
          </button>
          <button
            className="secondary"
            onClick={() => {
              setResetTarget(u);
              setResetPassword(generatePassword());
            }}
          >
            Reset pw
          </button>
        </span>
      ),
    },
  ];

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <Card title="Users">
        <p className="muted">
          Login accounts are backed by identities. Users are never deleted — deactivate instead, so
          the audit trail keeps its referential integrity. Passwords are set by an admin and must be
          changed on first login.
        </p>
        <div className="actions" style={{ marginBottom: 12 }}>
          <button
            onClick={() => {
              setAdding(true);
              setNewPassword(generatePassword());
            }}
          >
            Add user
          </button>
        </div>
        {rows === null ? (
          <p className="muted">Loading…</p>
        ) : (
          <DataTable
            viewKey="users"
            columns={columns}
            rows={rows}
            getRowKey={(u) => u.id}
            empty={<Empty>No users</Empty>}
          />
        )}
      </Card>

      {adding && (
        <Modal title="Add user" onClose={() => setAdding(false)}>
          <div className="form-grid">
            <label style={{ gridColumn: "1 / -1" }}>
              Identity (searches username / employee_id)
              <Typeahead
                lookup={lookupIdentities}
                onSelect={setIdentity}
                placeholder="Type a username or employee id…"
              />
            </label>
            <label>
              Role
              <select value={newRole} onChange={(e) => setNewRole(e.target.value as Role)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Initial password (min 8)
              <span className="row">
                <input
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  style={{ flex: 1 }}
                  autoComplete="off"
                />
                <button className="secondary" onClick={() => setNewPassword(generatePassword())}>
                  Generate
                </button>
              </span>
            </label>
          </div>
          <p className="muted">The user must change this password at first login.</p>
          <div className="actions">
            <button disabled={!identity || newPassword.length < 8 || busy} onClick={createUser}>
              {busy ? "Creating…" : "Create user"}
            </button>
            <button className="secondary" onClick={() => setAdding(false)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}

      {roleTarget && (
        <Modal title={`Change role - ${roleTarget.username ?? ""}`} onClose={() => setRoleTarget(null)}>
          <div className="form-grid">
            <label>
              New role
              <select value={roleValue} onChange={(e) => setRoleValue(e.target.value as Role)}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="muted">Applies on the user next request - no re-login needed.</p>
          <div className="actions">
            <button onClick={submitRole}>Save role</button>
            <button className="secondary" onClick={() => setRoleTarget(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}

      {resetTarget && (
        <Modal title={`Reset password - ${resetTarget.username ?? ""}`} onClose={() => setResetTarget(null)}>
          <div className="form-grid">
            <label>
              New password (min 8)
              <span className="row">
                <input
                  value={resetPassword}
                  onChange={(e) => setResetPassword(e.target.value)}
                  style={{ flex: 1 }}
                  autoComplete="off"
                />
                <button className="secondary" onClick={() => setResetPassword(generatePassword())}>
                  Generate
                </button>
              </span>
            </label>
          </div>
          <p className="muted">
            The user must change this password at next login. Communicate it over a secure channel -
            it is shown once after saving.
          </p>
          <div className="actions">
            <button disabled={resetPassword.length < 8} onClick={submitReset}>
              Reset password
            </button>
            <button className="secondary" onClick={() => setResetTarget(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}

      {reveal && (
        <Modal title="Copy the password now" onClose={() => setReveal(null)}>
          <p className="muted">
            This is the only time the password is shown in full. Username: <strong>{reveal.username}</strong>
          </p>
          <p className="mono key-box">{reveal.password}</p>
          <div className="actions">
            <button onClick={copyPassword}>{copied ? "Copied ✓" : "Copy"}</button>
            <button className="secondary" onClick={() => setReveal(null)}>
              Done
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
