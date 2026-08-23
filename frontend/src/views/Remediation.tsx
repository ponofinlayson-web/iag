import { useEffect, useState } from "react";
import { api } from "../api/client";
import type {
  RemediationAction,
  RemediationRule,
  RemediationSettings,
  ScimConfig,
} from "../api/client";
import { useAuth } from "../auth";
import { Badge, Card, Empty, errMsg, Modal } from "../components/ui";

const PRIVILEGES = ["low", "moderate", "high", "very_high"];
const STATUSES = ["pending_approval", "approved", "executing", "completed", "failed", "cancelled"];
const ENFORCE_TARGETS = ["remove_entitlement", "disable_account"];

function statusTone(status: string): "ok" | "warn" | "bad" | "neutral" {
  switch (status) {
    case "completed": return "ok";
    case "failed": return "bad";
    case "cancelled": return "neutral";
    case "pending_approval": return "warn";
    default: return "neutral"; // approved, executing
  }
}

function toUtc(s: string): Date {
  // Backend dates are naive-UTC isoformat; display math must not read local.
  return new Date(s.endsWith("Z") ? s : s + "Z");
}

export default function Remediation() {
  const { me } = useAuth();
  const isSystemAdmin = me?.role === "system_admin";
  const [rules, setRules] = useState<RemediationRule[] | null>(null);
  const [actions, setActions] = useState<RemediationAction[] | null>(null);
  const [settings, setSettings] = useState<RemediationSettings | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // scim settings panel (system_admin)
  const [scim, setScim] = useState<ScimConfig | null>(null);
  const [scimToken, setScimToken] = useState<string | null>(null);
  const [scimCopied, setScimCopied] = useState(false);
  const [confirmScimRevoke, setConfirmScimRevoke] = useState(false);
  const [syncingSource, setSyncingSource] = useState<number | null>(null);

  // rule form
  const [name, setName] = useState("");
  const [action, setAction] = useState("notify_owner");
  const [target, setTarget] = useState("remove_entitlement");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [pattern, setPattern] = useState("");
  const [privilege, setPrivilege] = useState("");
  const [requireApproval, setRequireApproval] = useState(false);
  const [regexOk, setRegexOk] = useState(true);
  const [sourceId, setSourceId] = useState("");
  const [sourcesList, setSourcesList] = useState<
    { id: number; name: string; source_type: string | null }[]
  >([]);

  function load() {
    api.remediation.rules().then((r) => setRules(r.items)).catch((e) => setError(e.message));
    api.remediation
      .actions(statusFilter ? { status: statusFilter } : {})
      .then((r) => setActions(r.items))
      .catch((e) => setError(e.message));
    api.remediation.settings().then(setSettings).catch((e) => setError(e.message));
    api.sources.list().then((r) => setSourcesList(r.items)).catch(() => undefined);
  }

  function loadScim() {
    if (isSystemAdmin) {
      api.scim.getConfig().then(setScim).catch(() => setScim(null));
    }
  }

  useEffect(load, []);
  useEffect(load, [statusFilter]);
  useEffect(loadScim, [isSystemAdmin]);

  useEffect(() => {
    if (!pattern) {
      setRegexOk(true);
      return;
    }
    try {
      new RegExp(pattern);
      setRegexOk(true);
    } catch {
      setRegexOk(false);
    }
  }, [pattern]);

  async function create() {
    setError("");
    setNotice("");
    try {
      await api.remediation.createRule({
        name,
        action,
        target: action === "enforce" ? target : null,
        webhook_url: action === "webhook" ? webhookUrl : null,
        entitlement_pattern: pattern || null,
        privilege_level: privilege || null,
        data_source_id: sourceId ? Number(sourceId) : null,
        // undefined = let the backend apply its defaults (enforce => ON)
        require_approval: action === "enforce" ? requireApproval || undefined : requireApproval,
      });
      setNotice(`Rule "${name}" created`);
      setName("");
      setWebhookUrl("");
      setPattern("");
      setPrivilege("");
      setRequireApproval(false);
      setTarget("remove_entitlement");
      setSourceId("");
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function toggle(rule: RemediationRule) {
    setError("");
    try {
      await api.remediation.updateRule(rule.id, {
        name: rule.name,
        description: rule.description,
        data_source_id: rule.data_source_id,
        privilege_level: rule.privilege_level,
        entitlement_pattern: rule.entitlement_pattern,
        action: rule.action,
        target: rule.target,
        webhook_url: rule.webhook_url,
        is_active: !rule.is_active,
        // the stored value IS explicit here - round-trip it unchanged
        require_approval: rule.require_approval,
      });
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function remove(rule: RemediationRule) {
    setError("");
    try {
      await api.remediation.deleteRule(rule.id);
      setNotice(`Rule "${rule.name}" deleted`);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function act(a: RemediationAction, op: "approve" | "cancel") {
    setError("");
    try {
      const r = await api.remediation.act(a.id, op);
      setNotice(`Action #${a.id} ${r.status}`);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function retry(a: RemediationAction) {
    setError("");
    try {
      await api.remediation.retry(a.id);
      setNotice(`Action #${a.id} requeued (attempt ${a.attempts + 1})`);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function saveSettings(next: RemediationSettings) {
    setError("");
    try {
      const r = await api.remediation.updateSettings(next);
      setSettings(r);
      setNotice("Settings saved");
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function toggleScim(enabled: boolean) {
    setError("");
    try {
      const r = await api.scim.updateConfig(enabled);
      setScim(r);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function generateScimToken() {
    setError("");
    try {
      const r = await api.scim.createToken();
      setScimToken(r.token);
      setScimCopied(false);
      loadScim();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function revokeScimToken() {
    setError("");
    setConfirmScimRevoke(false);
    try {
      await api.scim.revokeToken();
      setNotice("SCIM token revoked - the provisioning surface is now closed");
      loadScim();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  function copyScimToken() {
    if (!scimToken) return;
    navigator.clipboard
      .writeText(scimToken)
      .then(() => setScimCopied(true))
      .catch(() => setError("Clipboard unavailable - copy manually"));
  }

  async function syncNow(a: RemediationAction) {
    const srcId = a.snapshot.data_source_id;
    if (!srcId) return;
    setError("");
    setSyncingSource(srcId);
    try {
      const r = await api.sources.syncNow(srcId);
      setNotice(`Sync #${r.run_id} started for ${a.snapshot.data_source_name ?? `source ${srcId}`}`);
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setSyncingSource(null);
    }
  }

  const canCreate = name.trim().length > 0 && regexOk && (action !== "webhook" || webhookUrl.trim().length > 0);

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <Card title="Remediation settings">
        {settings && (
          <div className="row" style={{ flexWrap: "wrap", gap: 16 }}>
            <label className="row" style={{ gap: 6 }}>
              <input
                type="checkbox"
                checked={settings.enabled}
                onChange={(e) => void saveSettings({ ...settings!, enabled: e.target.checked })}
              />
              Enabled
            </label>
            <label className="row" style={{ gap: 6 }}>
              Default action
              <select
                value={settings.default_action}
                onChange={(e) => void saveSettings({ ...settings!, default_action: e.target.value })}
              >
                <option value="notify_owner">notify_owner</option>
                <option value="webhook">webhook</option>
              </select>
            </label>
            <label className="row" style={{ gap: 6 }}>
              <input
                type="checkbox"
                checked={settings.require_approval_for_high_risk}
                onChange={(e) =>
                  void saveSettings({ ...settings!, require_approval_for_high_risk: e.target.checked })
                }
              />
              Require approval for high risk
            </label>
          </div>
        )}
      </Card>
      {isSystemAdmin && (
        <Card title="SCIM provisioning">
          {scim === null ? (
            <p className="muted">Loading…</p>
          ) : (
            <div className="row" style={{ flexWrap: "wrap", gap: 16, alignItems: "center" }}>
              <label className="row" style={{ gap: 6 }}>
                <input
                  type="checkbox"
                  checked={scim.enabled}
                  onChange={(e) => void toggleScim(e.target.checked)}
                />
                Enabled
              </label>
              <span className="muted">
                Token:{" "}
                {scim.token_prefix ? (
                  <>
                    <code>{scim.token_prefix}…</code>{" "}
                    created {toUtc(scim.token_created_at!).toLocaleString()}
                  </>
                ) : (
                  "none (surface answers 503 until one is generated)"
                )}
              </span>
              <span className="row" style={{ gap: 8 }}>
                <button onClick={() => void generateScimToken()}>
                  {scim.token_prefix ? "Rotate token" : "Generate token"}
                </button>
                {scim.token_prefix && !confirmScimRevoke && (
                  <button className="secondary" onClick={() => setConfirmScimRevoke(true)}>
                    Revoke
                  </button>
                )}
                {confirmScimRevoke && (
                  <>
                    <button className="danger" onClick={() => void revokeScimToken()}>
                      Confirm revoke
                    </button>
                    <button className="secondary" onClick={() => setConfirmScimRevoke(false)}>
                      Cancel
                    </button>
                  </>
                )}
              </span>
            </div>
          )}
          <p className="muted" style={{ marginBottom: 0 }}>
            The provisioning endpoint is <code>/api/scim/v2</code>. The token is shown once at
            generation and stored hashed. Point your IdP at it with{" "}
            <code>Authorization: Bearer …</code>. The join key is whatever your IdP sends as{" "}
            <code>externalId</code> - pick a stable one (UPN or employee number), not a display
            name. See docs/admin-guide.md.
          </p>
        </Card>
      )}
      <Card title="New remediation rule">
        <p className="muted">
          Rules fire when a reviewer revokes access. All filters are ANDed; an empty filter matches all.
        </p>
        <div className="row" style={{ marginBottom: 8 }}>
          <input placeholder="Rule name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="notify_owner">notify_owner</option>
            <option value="webhook">webhook</option>
            <option value="enforce">enforce</option>
          </select>
        </div>
        {action === "webhook" && (
          <input
            placeholder="Webhook URL (https://…)"
            value={webhookUrl}
            onChange={(e) => setWebhookUrl(e.target.value)}
            style={{ marginBottom: 8, width: "100%" }}
          />
        )}
        {action === "enforce" && (
          <div style={{ marginBottom: 8 }}>
            <div className="row">
              <select value={target} onChange={(e) => setTarget(e.target.value)}>
                {ENFORCE_TARGETS.map((t) => (
                  <option key={t} value={t}>{t}</option>
                ))}
              </select>
              <span className="muted">directory write-back target</span>
            </div>
            <p className="muted" style={{ marginBottom: 0 }}>
              remove_entitlement needs the entitlement name to be the directory group name.
              disable_account writes to the account attribute the connector matches on. SQL
              sources need admin-supplied statements in the connector config. Enforcement
              requires approval by default.
            </p>
          </div>
        )}
        <div className="row" style={{ marginBottom: 8 }}>
          <select
            value={sourceId}
            onChange={(e) => setSourceId(e.target.value)}
            aria-label="Restrict to source"
          >
            <option value="">all sources</option>
            {sourcesList.map((s) => (
              <option key={s.id} value={s.id}>
                #{s.id} {s.name} ({s.source_type})
              </option>
            ))}
          </select>
          <span className="muted">restrict rule to one source (optional)</span>
        </div>
        <div className="row" style={{ marginBottom: 8 }}>
          <input
            placeholder="Entitlement regex (optional)"
            value={pattern}
            onChange={(e) => setPattern(e.target.value)}
            style={{ flex: 1 }}
          />
          <select value={privilege} onChange={(e) => setPrivilege(e.target.value)}>
            <option value="">any privilege</option>
            {PRIVILEGES.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </div>
        {!regexOk && <p className="error-text">Invalid regex</p>}
        <label className="row" style={{ gap: 6, marginBottom: 8 }}>
          <input
            type="checkbox"
            checked={requireApproval}
            onChange={(e) => setRequireApproval(e.target.checked)}
          />
          Require approval
        </label>
        <button disabled={!canCreate} onClick={() => void create()}>
          Create rule
        </button>
      </Card>
      <Card title={`Rules${rules ? ` (${rules.length})` : ""}`}>
        {rules && rules.length === 0 && <Empty>No remediation rules yet.</Empty>}
        {rules && rules.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Filters</th>
                <th>Action</th>
                <th>Approval</th>
                <th>Stats</th>
                <th>Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td className="muted">
                    {[
                      r.privilege_level,
                      r.entitlement_pattern,
                      r.data_source_id != null ? `source #${r.data_source_id}` : null,
                    ].filter(Boolean).join(" · ") || "catch-all"}
                  </td>
                   <td>
                    {r.action}
                    {r.action === "webhook" && r.webhook_url && (
                      <span className="muted"> → {r.webhook_url.slice(0, 40)}</span>
                    )}
                    {r.action === "enforce" && (
                      <span className="muted"> → {r.target ?? "remove_entitlement"}</span>
                    )}
                  </td>
                  <td>{r.require_approval ? "required" : "—"}</td>
                  <td className="muted">
                    trig {r.times_triggered} · ok {r.times_executed} · fail {r.times_failed}
                  </td>
                  <td>
                    <button className="secondary" onClick={() => void toggle(r)}>
                      {r.is_active ? "Deactivate" : "Activate"}
                    </button>
                  </td>
 <td>
                    <button className="danger" onClick={() => void remove(r)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <Card title={`Action queue${actions ? ` (${actions.length})` : ""}`}>
        <div className="row" style={{ marginBottom: 8 }}>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
            <option value="">all statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        {actions && actions.length === 0 && <Empty>No actions{statusFilter ? ` with status ${statusFilter}` : ""}.</Empty>}
        {actions && actions.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Status</th>
                <th>Type</th>
                <th>Target</th>
                <th>Campaign</th>
                <th>Rule</th>
                <th>Attempts</th>
                <th>Result</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {actions.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td><Badge tone={statusTone(a.status)}>{a.status}</Badge></td>
                  <td>
                    {a.action_type === "enforce" ? (
                      <Badge tone="warn">enforce</Badge>
                    ) : (
                      a.action_type
                    )}
                  </td>
                  <td>
                    {a.action_type === "enforce" && (
                      <div className="muted" style={{ marginBottom: 2 }}>
                        target: {a.snapshot.target ?? "remove_entitlement"}
                      </div>
                    )}
                    {a.snapshot.entitlement_name ?? "?"} → {a.snapshot.identity_name ?? "?"}
                    <span className="muted"> ({a.snapshot.account_value ?? "?"})</span>
                  </td>
                  <td>{a.snapshot.campaign_name ?? a.snapshot.campaign_id ?? "—"}</td>
                  <td>{a.rule_name ?? "default"}</td>
                  <td>{a.attempts}</td>
                  <td className="muted" style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {a.result ?? "—"}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {a.status === "pending_approval" && (
                      <button onClick={() => void act(a, "approve")}>Approve</button>
                    )}
                    {!["completed", "cancelled"].includes(a.status) && (
                      <button className="secondary" onClick={() => void act(a, "cancel")}>Cancel</button>
                    )}
                    {a.status === "failed" && (
                      <button onClick={() => void retry(a)}>Retry</button>
                    )}
                    {a.action_type === "enforce" && a.status === "completed" && (
                      <button
                        className="secondary"
                        disabled={!a.snapshot.data_source_id || syncingSource !== null}
                        title={
                          a.snapshot.data_source_id
                            ? "Mirror updates at the next sync - run it now to close the drift window"
                            : "Source unknown - sync from the Sources page"
                        }
                        onClick={() => void syncNow(a)}
                      >
                        {syncingSource !== null ? "Syncing…" : "Sync now"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {scimToken && (
        <Modal title="Copy your SCIM token now" onClose={() => setScimToken(null)}>
          <p className="muted">
            This is the only time the full token is shown. It is stored hashed and cannot be
            recovered. Rotating replaces it (the old token stops working immediately). The
            join key for provisioned users is whatever your IdP sends as{" "}
            <code>externalId</code> - pick a stable one (UPN or employee number), not a
            display name.
          </p>
          <p className="mono key-box">{scimToken}</p>
          <div className="actions">
            <button onClick={copyScimToken}>{scimCopied ? "Copied ✓" : "Copy"}</button>
            <button className="secondary" onClick={() => setScimToken(null)}>
              I stored it
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
