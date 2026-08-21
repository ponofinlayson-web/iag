import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RemediationAction, RemediationRule, RemediationSettings } from "../api/client";
import { Badge, Card, Empty, errMsg } from "../components/ui";

const PRIVILEGES = ["low", "moderate", "high", "very_high"];
const STATUSES = ["pending_approval", "approved", "executing", "completed", "failed", "cancelled"];

function statusTone(status: string): "ok" | "warn" | "bad" | "neutral" {
  switch (status) {
    case "completed": return "ok";
    case "failed": return "bad";
    case "cancelled": return "neutral";
    case "pending_approval": return "warn";
    default: return "neutral"; // approved, executing
  }
}

export default function Remediation() {
  const [rules, setRules] = useState<RemediationRule[] | null>(null);
  const [actions, setActions] = useState<RemediationAction[] | null>(null);
  const [settings, setSettings] = useState<RemediationSettings | null>(null);
  const [statusFilter, setStatusFilter] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // rule form
  const [name, setName] = useState("");
  const [action, setAction] = useState("notify_owner");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [pattern, setPattern] = useState("");
  const [privilege, setPrivilege] = useState("");
  const [requireApproval, setRequireApproval] = useState(false);
  const [regexOk, setRegexOk] = useState(true);

  function load() {
    api.remediation.rules().then((r) => setRules(r.items)).catch((e) => setError(e.message));
    api.remediation
      .actions(statusFilter ? { status: statusFilter } : {})
      .then((r) => setActions(r.items))
      .catch((e) => setError(e.message));
    api.remediation.settings().then(setSettings).catch((e) => setError(e.message));
  }

  useEffect(load, []);
  useEffect(load, [statusFilter]);

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
        webhook_url: action === "webhook" ? webhookUrl : null,
        entitlement_pattern: pattern || null,
        privilege_level: privilege || null,
        require_approval: requireApproval,
      });
      setNotice(`Rule "${name}" created`);
      setName("");
      setWebhookUrl("");
      setPattern("");
      setPrivilege("");
      setRequireApproval(false);
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
        webhook_url: rule.webhook_url,
        is_active: !rule.is_active,
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
      <Card title="New remediation rule">
        <p className="muted">
          Rules fire when a reviewer revokes access. All filters are ANDed; an empty filter matches all.
        </p>
        <div className="row" style={{ marginBottom: 8 }}>
          <input placeholder="Rule name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
          <select value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="notify_owner">notify_owner</option>
            <option value="webhook">webhook</option>
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
                    ].filter(Boolean).join(" · ") || "catch-all"}
                  </td>
 <td>
                    {r.action}
                    {r.action === "webhook" && r.webhook_url && (
                      <span className="muted"> → {r.webhook_url.slice(0, 40)}</span>
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
                  <td>{a.action_type}</td>
                  <td>
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
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
