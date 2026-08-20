import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Account, Source, SyncRunView } from "../api/client";
import { Badge, Card, privilegeTone, errMsg } from "../components/ui";

interface PagedAcc {
  total: number;
  items: Account[];
}

type Msg = { setError: (s: string) => void; setNotice: (s: string) => void };

export default function Sources() {
  const [sources, setSources] = useState<Source[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [accounts, setAccounts] = useState<PagedAcc | null>(null);
  const [syncSource, setSyncSource] = useState<Source | null>(null);

  async function loadSources() {
    try {
      setSources((await api.sources.list()).items);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  useEffect(() => {
    void loadSources();
  }, []);

  useEffect(() => {
    if (selected != null) {
      api.sources.accounts(selected, { page_size: 100 }).then(setAccounts).catch((e: unknown) => setError(errMsg(e)));
    }
  }, [selected]);

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <SourceForm onCreate={loadSources} setError={setError} setNotice={setNotice} />
      <Card title="Sources">
        {!sources ? (
          <p className="muted">Loading…</p>
        ) : sources.length === 0 ? (
          <p className="empty">No sources yet. Create one above, then upload a CSV snapshot or configure a connector.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Type</th>
                <th>Accounts</th>
                <th>Unlinked</th>
                <th>Last sync</th>
                <th>Connector</th>
                <th>Upload</th>
                <th>Bulk link</th>
              </tr>
            </thead>
            <tbody>
              {sources.map((s) => (
                <SourceRow
                  key={s.id}
                  source={s}
                  reload={loadSources}
                  setError={setError}
                  setNotice={setNotice}
                  onSelect={() => setSelected(s.id)}
                  onConfigure={() => setSyncSource(s)}
                />
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {syncSource != null && (
        <ConnectorPanel
          source={syncSource}
          onClose={() => setSyncSource(null)}
          reload={loadSources}
          setError={setError}
          setNotice={setNotice}
        />
      )}
      {selected != null && accounts && (
        <Card title={`Accounts — source ${selected} (${accounts.total})`}>
          <table>
            <thead>
              <tr>
                <th>Account</th>
                <th>Entitlement</th>
                <th>Privilege</th>
                <th>Identity</th>
              </tr>
            </thead>
            <tbody>
              {accounts.items.map((a) => (
                <tr key={a.id}>
                  <td>{a.account_value}</td>
                  <td>{a.entitlement_name}</td>
                  <td>
                    {a.privilege_level ? (
                      <Badge tone={privilegeTone(a.privilege_level)}>{a.privilege_level}</Badge>
                    ) : (
                      "—"
                    )}
                  </td>
                  <td>{a.identity_id != null ? `#${a.identity_id}` : <span className="muted">unlinked</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  );
}

function SourceForm({ onCreate, setError, setNotice }: Msg & { onCreate: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("csv");
  const [owner, setOwner] = useState("");

  async function submit() {
    if (!name.trim()) return;
    try {
      await api.sources.create({ name, source_type: type, owner_employee_id: owner || undefined });
      setNotice(`Source "${name}" created`);
      setName("");
      setOwner("");
      await onCreate();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  return (
    <Card title="Create source">
      <div className="form-grid">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="App Directory" />
        </label>
        <label>
          Type
          <select value={type} onChange={(e) => setType(e.target.value)}>
            <option value="csv">csv (upload)</option>
            <option value="xlsx">xlsx (upload)</option>
            <option value="ldap">ldap (live connector)</option>
            <option value="entra">entra (live connector)</option>
            <option value="sql">sql (live connector)</option>
          </select>
        </label>
        <label>
          Owner employee ID
          <input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="E-ADMIN" />
        </label>
      </div>
      <button onClick={() => void submit()}>Create</button>
    </Card>
  );
}

function SourceRow({
  source,
  reload,
  setError,
  setNotice,
  onSelect,
  onConfigure,
}: Msg & { source: Source; reload: () => Promise<void>; onSelect: () => void; onConfigure: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    try {
      const r = await api.sources.uploadCsv(source.id, file);
      setNotice(`Uploaded to ${source.name}: ${r.accounts_created} accounts, ${r.entitlements_created} entitlements`);
      await reload();
    } catch (e) {
      setError(errMsg(e));
    }
  }
  async function bulkLink(match: "username" | "email") {
    try {
      const r = await api.sources.bulkLink(source.id, match);
      setNotice(`Bulk linked ${r.linked}/${r.considered} by ${match}`);
      await reload();
    } catch (e) {
      setError(errMsg(e));
    }
  }
  async function syncNow() {
    try {
      const r = await api.sources.syncNow(source.id);
      setNotice(`Sync run #${r.run_id} enqueued for ${source.name}`);
      await reload();
    } catch (e) {
      setError(errMsg(e));
    }
  }
  const conn = source.connector;
  const isConnector = source.source_type === "ldap" || source.source_type === "entra" || source.source_type === "sql";
  return (
    <tr>
      <td>{source.id}</td>
      <td>
        <a onClick={onSelect} style={{ cursor: "pointer" }}>
          {source.name}
        </a>
      </td>
      <td>{source.source_type}</td>
      <td>{source.account_count}</td>
      <td>{source.unlinked_count}</td>
      <td>
        {conn?.last_run_status ? (
          <Badge tone={syncTone(conn.last_run_status)}>{conn.last_run_status}</Badge>
        ) : (
          <span className="muted">never</span>
        )}
      </td>
      <td>
        {isConnector ? (
          <>
            {conn?.configured ? <Badge tone="ok">configured</Badge> : <Badge tone="neutral">not configured</Badge>}{" "}
            <button className="secondary" onClick={onConfigure}>
              Configure
            </button>{" "}
            <button className="secondary" onClick={() => void syncNow()} disabled={!conn?.configured}>
              Sync now
            </button>
          </>
        ) : (
          <span className="muted">upload only</span>
        )}
      </td>
      <td>
        <input ref={fileRef} type="file" accept=".csv" />
        <button className="secondary" onClick={() => void upload()}>
          Upload
        </button>
      </td>
      <td>
        <button className="secondary" onClick={() => void bulkLink("username")}>
          By username
        </button>{" "}
        <button className="secondary" onClick={() => void bulkLink("email")}>
          By email
        </button>
      </td>
    </tr>
  );
}

const CONNECTOR_FIELDS: Record<string, { key: string; label: string; placeholder?: string }[]> = {
  ldap: [
    { key: "url", label: "Server URL", placeholder: "ldap://dc01.corp:389" },
    { key: "base_dn", label: "Base DN", placeholder: "dc=corp,dc=example,dc=com" },
    { key: "bind_dn", label: "Bind DN (optional)", placeholder: "cn=svc-iag,ou=svc,dc=corp,dc=example,dc=com" },
    { key: "filter", label: "Search filter (optional)", placeholder: "(objectClass=person)" },
    { key: "account_attr", label: "Account attribute (optional)", placeholder: "sAMAccountName" },
    { key: "entitlements_attr", label: "Entitlements attribute (optional)", placeholder: "memberOf" },
  ],
  entra: [
    { key: "tenant_id", label: "Tenant ID" },
    { key: "client_id", label: "Client (app) ID" },
  ],
  sql: [
    { key: "url", label: "Database URL", placeholder: "postgresql+psycopg2://user@host/db" },
    { key: "query", label: "SELECT query", placeholder: "SELECT account, entitlement, privilege FROM access" },
  ],
};

const SECRET_LABEL: Record<string, string> = {
  ldap: "Bind password",
  entra: "Client secret",
  sql: "URL password ($SECRET placeholder)",
};

function syncTone(status: string): "ok" | "warn" | "bad" | "neutral" {
  switch (status) {
    case "done":
      return "ok";
    case "pending":
    case "syncing":
      return "warn";
    case "failed":
      return "bad";
    default:
      return "neutral";
  }
}

function ConnectorPanel({
  source,
  onClose,
  reload,
  setError,
  setNotice,
}: Msg & { source: Source; onClose: () => void; reload: () => Promise<void> }) {
  const fields = CONNECTOR_FIELDS[source.source_type ?? ""] ?? [];
  const [config, setConfig] = useState<Record<string, string>>({});
  const [secret, setSecret] = useState("");
  const [interval, setIntervalInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api.sources.configureConnector(source.id, {
        config,
        secret: secret || undefined,
        sync_interval_minutes: interval ? Number(interval) : undefined,
      });
      setNotice(`Connector for ${source.name} validated and saved`);
      setSecret("");
      await reload();
      onClose();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={`Connector — ${source.name} (${source.source_type})`}>
      <div className="form-grid">
        {fields.map((f) => (
          <label key={f.key}>
            {f.label}
            <input
              value={config[f.key] ?? ""}
              onChange={(e) => setConfig({ ...config, [f.key]: e.target.value })}
              placeholder={f.placeholder ?? ""}
            />
          </label>
        ))}
        <label>
          {SECRET_LABEL[source.source_type ?? ""] ?? "Secret"}
          <input
            type="password"
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="write-only; leave blank to keep existing"
          />
        </label>
        <label>
          Sync interval (minutes, empty = manual only)
          <input value={interval} onChange={(e) => setIntervalInput(e.target.value)} placeholder="60" />
        </label>
      </div>
      <p className="muted">
        Saving runs a live validation (bind / token / LIMIT 1 query) before anything is stored. The server stores the
        secret; it is never returned by the API.
      </p>
      <button onClick={() => void save()} disabled={busy}>
        {busy ? "Validating…" : "Validate & save"}
      </button>{" "}
      <button className="secondary" onClick={onClose}>
        Cancel
      </button>{" "}
      <button className="secondary" onClick={() => setShowHistory(!showHistory)}>
        {showHistory ? "Hide history" : "Run history"}
      </button>
      {showHistory && <RunHistory sourceId={source.id} setError={setError} />}
    </Card>
  );
}

function RunHistory({ sourceId, setError }: { sourceId: number; setError: (s: string) => void }) {
  const [runs, setRuns] = useState<SyncRunView[] | null>(null);

  useEffect(() => {
    api.sources
      .syncs(sourceId, { page_size: 50 })
      .then((p) => setRuns(p.items))
      .catch((e: unknown) => setError(errMsg(e)));
  }, [sourceId]);

  async function cancel(runId: number) {
    try {
      await api.syncs.cancel(runId);
      const p = await api.sources.syncs(sourceId, { page_size: 50 });
      setRuns(p.items);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  return (
    <Card title={`Sync runs — source ${sourceId}`}>
      {!runs ? (
        <p className="muted">Loading…</p>
      ) : runs.length === 0 ? (
        <p className="empty">No sync runs yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Run</th>
              <th>Status</th>
              <th>Trigger</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Counts</th>
              <th>Error</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.id}>
                <td>#{r.id}</td>
                <td>
                  <Badge tone={syncTone(r.status)}>{r.status}</Badge>
                </td>
                <td>{r.triggered_by}</td>
                <td>{r.started_at ?? "—"}</td>
                <td>{r.finished_at ?? "—"}</td>
                <td>
                  {r.stats
                    ? `+${r.stats.accounts_created ?? 0} acc / ${r.stats.entitlements_created ?? 0} ent / miss ${r.stats.missing_from_snapshot ?? 0}`
                    : "—"}
                </td>
                <td className="muted">{r.error ?? ""}</td>
                <td>
                  {(r.status === "pending" || r.status === "syncing") && (
                    <button className="secondary" onClick={() => void cancel(r.id)}>
                      Cancel
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
