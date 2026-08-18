import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Entitlement, SodRule } from "../api/client";
import { Badge, Card, Empty, errMsg, privilegeTone } from "../components/ui";

const SEVERITIES = ["low", "moderate", "high", "very_high"];

export default function SodRules() {
  const [rules, setRules] = useState<SodRule[] | null>(null);
  const [ents, setEnts] = useState<Entitlement[]>([]);
  const [entQuery, setEntQuery] = useState("");
  const [name, setName] = useState("");
  const [aId, setAId] = useState(0);
  const [bId, setBId] = useState(0);
  const [severity, setSeverity] = useState("high");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  function load() {
    api.sod.rules().then((r) => setRules(r.items)).catch((e) => setError(e.message));
  }

  useEffect(load, []);
  useEffect(() => {
    api.entitlements.list({ q: entQuery, page_size: 100 }).then((r) => setEnts(r.items)).catch(() => undefined);
  }, [entQuery]);

  async function create() {
    setError("");
    setNotice("");
    try {
      await api.sod.createRule({ name, entitlement_a_id: aId, entitlement_b_id: bId, severity });
      setNotice(`Rule "${name}" created`);
      setName("");
      setAId(0);
      setBId(0);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

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

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <Card title="New SoD rule">
        <p className="muted">An identity holding both entitlements (across any sources) is flagged during campaign preview and review.</p>
        <div className="row" style={{ marginBottom: 8 }}>
          <input placeholder="Rule name" value={name} onChange={(e) => setName(e.target.value)} style={{ flex: 1 }} />
          <select value={severity} onChange={(e) => setSeverity(e.target.value)}>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <input
          placeholder="Filter entitlements…"
          value={entQuery}
          onChange={(e) => setEntQuery(e.target.value)}
          style={{ marginBottom: 8 }}
        />
        <div className="row" style={{ marginBottom: 8 }}>
          <select value={aId} onChange={(e) => setAId(Number(e.target.value))} style={{ flex: 1 }}>
            <option value={0}>— entitlement A —</option>
            {ents.map((e) => (
              <option key={e.id} value={e.id}>{e.name} ({e.catalog_id})</option>
            ))}
          </select>
          <select value={bId} onChange={(e) => setBId(Number(e.target.value))} style={{ flex: 1 }}>
            <option value={0}>— entitlement B —</option>
            {ents.map((e) => (
              <option key={e.id} value={e.id}>{e.name} ({e.catalog_id})</option>
            ))}
          </select>
        </div>
        <button disabled={!name || !aId || !bId || aId === bId} onClick={() => void create()}>
          Create rule
        </button>
      </Card>
      <Card title={`Rules${rules ? ` (${rules.length})` : ""}`}>
        {rules && rules.length === 0 && <Empty>No SoD rules yet.</Empty>}
        {rules && rules.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Entitlement A</th>
                <th>Entitlement B</th>
                <th>Severity</th>
                <th>Active</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {rules.map((r) => (
                <tr key={r.id}>
                  <td>{r.name}</td>
                  <td>{r.entitlement_a_name ?? `#${r.entitlement_a_id}`}</td>
                  <td>{r.entitlement_b_name ?? `#${r.entitlement_b_id}`}</td>
                  <td><Badge tone={privilegeTone(r.severity)}>{r.severity}</Badge></td>
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
    </div>
  );
}
