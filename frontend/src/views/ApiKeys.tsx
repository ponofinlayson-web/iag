import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ApiKeyRow } from "../api/client";
import { Badge, Card, Empty, errMsg, Modal } from "../components/ui";

const KEY_ROLES = ["auditor", "report_viewer"];

function toUtc(s: string): Date {
  // Backend dates are naive-UTC isoformat; status math must not read them as local.
  return new Date(s.endsWith("Z") ? s : s + "Z");
}

type Status = { label: string; tone: "ok" | "warn" | "bad" | "neutral" };

function keyStatus(r: ApiKeyRow): Status {
  if (!r.is_active) return { label: "revoked", tone: "neutral" };
  if (r.expires_at && toUtc(r.expires_at) <= new Date()) return { label: "expired", tone: "warn" };
  return { label: "active", tone: "ok" };
}

export default function ApiKeys() {
  const [rows, setRows] = useState<ApiKeyRow[] | null>(null);
  const [error, setError] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState("auditor");
  const [expires, setExpires] = useState("");
  const [creating, setCreating] = useState(false);
  const [reveal, setReveal] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmId, setConfirmId] = useState<number | null>(null);

  function load() {
    api.apiKeys
      .list()
      .then((r) => setRows(r.items))
      .catch((e) => setError(errMsg(e)));
  }

  useEffect(load, []);

  function create() {
    setError("");
    setCreating(true);
    api.apiKeys
      .create({
        name: name.trim(),
        role,
        expires_at: expires ? new Date(expires + "T12:00:00Z").toISOString() : null,
      })
      .then((r) => {
        setReveal(r.key);
        setCopied(false);
        setName("");
        setExpires("");
        load();
      })
      .catch((e) => setError(errMsg(e)))
      .finally(() => setCreating(false));
  }

  function revoke(id: number) {
    setError("");
    setConfirmId(null);
    api.apiKeys
      .revoke(id)
      .then(load)
      .catch((e) => setError(errMsg(e)));
  }

  function copyKey() {
    if (!reveal) return;
    navigator.clipboard
      .writeText(reveal)
      .then(() => setCopied(true))
      .catch(() => setError("Clipboard unavailable - copy manually"));
  }

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <Card title="API keys">
        <p className="muted">
          Bearer tokens for read-only machine access (report pulls, health checks). The full key is
          shown once at creation - only a prefix is stored afterwards. Revoke is permanent; to
          rotate, create a new key and revoke the old one.
        </p>
        <div className="form-grid" style={{ maxWidth: 480 }}>
          <label>
            Name
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. siem-export" />
          </label>
          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value)}>
              {KEY_ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
          <label>
            Expires (optional)
            <input type="date" value={expires} onChange={(e) => setExpires(e.target.value)} />
          </label>
          <div className="actions">
            <button disabled={!name.trim() || creating} onClick={create}>
              {creating ? "Creating…" : "Create key"}
            </button>
          </div>
        </div>
        {rows === null ? (
          <p className="muted">Loading…</p>
        ) : rows.length === 0 ? (
          <Empty>No API keys yet</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Prefix</th>
                <th>Role</th>
                <th>Status</th>
                <th>Expires</th>
                <th>Last used</th>
                <th>Created</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const st = keyStatus(r);
                return (
                  <tr key={r.id}>
                    <td>{r.name}</td>
                    <td className="mono">{r.key_prefix}…</td>
                    <td>
                      <Badge tone="neutral">{r.role}</Badge>
                    </td>
                    <td>
                      <Badge tone={st.tone}>{st.label}</Badge>
                    </td>
                    <td>{r.expires_at ? toUtc(r.expires_at).toLocaleDateString() : "never"}</td>
                    <td>{r.last_used_at ? toUtc(r.last_used_at).toLocaleString() : "—"}</td>
                    <td>{r.created_at ? toUtc(r.created_at).toLocaleString() : "—"}</td>
                    <td>
                      {confirmId === r.id ? (
                        <span className="row">
                          <button className="danger" onClick={() => revoke(r.id)}>
                            Confirm revoke
                          </button>
                          <button className="secondary" onClick={() => setConfirmId(null)}>
                            Cancel
                          </button>
                        </span>
                      ) : (
                        <button
                          className="secondary"
                          disabled={!r.is_active}
                          onClick={() => setConfirmId(r.id)}
                        >
                          Revoke
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      {reveal && (
        <Modal title="Copy your API key now" onClose={() => setReveal(null)}>
          <p className="muted">
            This is the only time the full key is shown. It is stored hashed and cannot be
            recovered. Use it as <code>Authorization: Bearer …</code>.
          </p>
          <p className="mono key-box">{reveal}</p>
          <div className="actions">
            <button onClick={copyKey}>{copied ? "Copied ✓" : "Copy"}</button>
            <button className="secondary" onClick={() => setReveal(null)}>
              I stored it
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
