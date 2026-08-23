import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Entitlement, SodRule, SodRunResult } from "../api/client";
import { Badge, Card, Empty, errMsg, Modal, privilegeTone } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";

const SEVERITIES = ["low", "moderate", "high", "very_high"];

export default function SodRules() {
  const [rules, setRules] = useState<SodRule[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [runResult, setRunResult] = useState<SodRunResult | null>(null);

  function load() {
    api.sod.rules().then((r) => setRules(r.items)).catch((e) => setError(e.message));
  }

  useEffect(load, []);

  async function toggle(rule: SodRule) {
    setError("");
    try {
      await api.sod.updateRule(rule.id, {
        name: rule.name,
        description: rule.description,
        entitlement_a_id: rule.entitlement_a_id,
        entitlement_b_id: rule.entitlement_b_id,
        severity: rule.severity,
        is_active: !rule.is_active,
      });
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function remove(rule: SodRule) {
    setError("");
    try {
      await api.sod.deleteRule(rule.id);
      setNotice(`Rule "${rule.name}" deleted`);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function run(rule: SodRule) {
    setError("");
    setNotice("");
    try {
      const r = await api.sod.runRule(rule.id);
      setRunResult(r);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  const columns: Column<SodRule>[] = [
    {
      key: "id",
      label: "ID",
      pinned: true,
      sortable: false,
      value: (r) => r.id,
    },
    {
      key: "name",
      label: "Name",
      pinned: true,
      filter: "text",
    },
    { key: "entitlement_a_name", label: "Entitlement A", filter: "text" },
    { key: "entitlement_b_name", label: "Entitlement B", filter: "text" },
    {
      key: "severity",
      label: "Severity",
      filter: "select",
      render: (r) => <Badge tone={privilegeTone(r.severity)}>{r.severity}</Badge>,
    },
    {
      key: "is_active",
      label: "Active",
      filter: "select",
      value: (r) => (r.is_active ? "active" : "inactive"),
      render: (r) => (r.is_active ? <Badge tone="ok">active</Badge> : <Badge tone="neutral">inactive</Badge>),
    },
    {
      key: "last_run",
      label: "Last run",
      filter: "select",
      value: (r) =>
        r.last_run ? `${r.last_run.violation_count} violations` : "never run",
      render: (r) =>
        r.last_run ? (
          <span>
            <Badge tone={r.last_run.violation_count > 0 ? "bad" : "ok"}>
              {r.last_run.violation_count} violations
            </Badge>{" "}
            <span className="muted">{r.last_run.computed_at?.slice(0, 19).replace("T", " ")}</span>
          </span>
        ) : (
          <span className="muted">never run</span>
        ),
    },
    {
      key: "actions",
      label: "",
      sortable: false,
      render: (r) => (
        <>
          <button className="secondary" onClick={() => void run(r)}>
            Run
          </button>{" "}
          <button className="secondary" onClick={() => void toggle(r)}>
            {r.is_active ? "Deactivate" : "Activate"}
          </button>{" "}
          <button className="danger" onClick={() => void remove(r)}>
            Delete
          </button>
        </>
      ),
    },
  ];

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => setCreating(true)}>Create rule</button>
      </div>
      <Card title={`Rules${rules ? ` (${rules.length})` : ""}`}>
        {!rules ? (
          <p className="muted">Loading.</p>
        ) : rules.length === 0 ? (
          <Empty>
            No SoD rules yet. An identity holding both entitlements of a rule (across any sources) is flagged during
            campaign preview and review.
          </Empty>
        ) : (
          <DataTable viewKey="sod-rules" columns={columns} rows={rules} getRowKey={(r) => r.id} searchable />
        )}
      </Card>
      {creating && <CreateRuleModal onClose={() => setCreating(false)} onCreated={load} setError={setError} />}
      {runResult && <RunResultModal result={runResult} onClose={() => setRunResult(null)} />}
    </div>
  );
}

function CreateRuleModal({
  onClose,
  onCreated,
  setError,
}: {
  onClose: () => void;
  onCreated: () => void;
  setError: (s: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [severity, setSeverity] = useState("high");
  const [aId, setAId] = useState(0);
  const [bId, setBId] = useState(0);
  const [ents, setEnts] = useState<Entitlement[]>([]);
  const [entQuery, setEntQuery] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => {
      api.entitlements
        .list({ q: entQuery, page_size: 100 })
        .then((r) => setEnts(r.items))
        .catch(() => undefined);
    }, 250);
    return () => window.clearTimeout(t);
  }, [entQuery]);

  async function create() {
    setBusy(true);
    try {
      await api.sod.createRule({
        name,
        description: description || undefined,
        entitlement_a_id: aId,
        entitlement_b_id: bId,
        severity,
      });
      onClose();
      onCreated();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  function entitlementOptions(placeholder: string) {
    return (
      <>
        <option value={0}>{placeholder}</option>
        {ents.map((e) => (
          <option key={e.id} value={e.id}>
            {e.name} ({e.catalog_id})
          </option>
        ))}
      </>
    );
  }

  return (
    <Modal title="Create SoD rule" onClose={onClose} wide>
      <p className="muted">
        An identity holding both entitlements (across any sources) is flagged during campaign preview and review.
      </p>
      <div className="form-grid">
        <label>
          Rule name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Payments vs ERP Deploy" autoFocus />
        </label>
        <label>
          Severity
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label>
          Description (optional)
          <input value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
      </div>
      <label style={{ display: "flex", flexDirection: "column", gap: 4, fontSize: 12, color: "var(--muted)", marginBottom: 8 }}>
        Filter entitlements
        <input value={entQuery} onChange={(e) => setEntQuery(e.target.value)} placeholder="Type to filter entitlements" />
      </label>
      <div className="form-grid">
        <label>
          Entitlement A
          <select value={aId} onChange={(e) => setAId(Number(e.target.value))} style={{ width: "100%" }}>
            {entitlementOptions("- select entitlement A -")}
          </select>
        </label>
        <label>
          Entitlement B
          <select value={bId} onChange={(e) => setBId(Number(e.target.value))} style={{ width: "100%" }}>
            {entitlementOptions("- select entitlement B -")}
          </select>
        </label>
      </div>
      <p className="muted">Use the entitlement filter above to narrow long lists.</p>
      <div className="actions">
        <button onClick={() => void create()} disabled={busy || !name.trim() || !aId || !bId || aId === bId}>
          {busy ? "Creating." : "Create rule"}
        </button>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}

function RunResultModal({ result, onClose }: { result: SodRunResult; onClose: () => void }) {
  return (
    <Modal title={`Run ${result.run_id.slice(0, 8)} - ${result.violation_count} violations`} onClose={onClose} wide>
      {result.violation_count === 0 ? (
        <Empty>No violations. No identity holds both entitlements of this rule.</Empty>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Identity</th>
              <th>Department</th>
              <th>Entitlement pair</th>
              <th>Severity</th>
            </tr>
          </thead>
          <tbody>
            {result.violations.map((v) => (
              <tr key={`${v.identity_id}-${v.rule_id}`}>
                <td>
                  {v.employee_id}
                  {v.identity_name ? ` (${v.identity_name})` : ""}
                </td>
                <td>{v.identity_department ?? "-"}</td>
                <td>
                  {v.entitlement_a} + {v.entitlement_b}
                </td>
                <td>
                  <Badge tone={privilegeTone(v.severity)}>{v.severity}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Modal>
  );
}
