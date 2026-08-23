import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Account, Source, SyncRunView } from "../api/client";
import { Badge, Card, errMsg, Modal, privilegeTone, Typeahead, type TypeaheadItem } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";

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
  const [creating, setCreating] = useState(false);

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

  const columns: Column<Source>[] = [
    { key: "id", label: "ID", pinned: true, sortable: false, value: (s) => s.id },
    {
      key: "name",
      label: "Name",
      pinned: true,
      filter: "text",
      render: (s) => (
        <a onClick={() => setSelected(s.id)} style={{ cursor: "pointer" }}>
          {s.name}
        </a>
      ),
    },
    { key: "source_type", label: "Type", filter: "select" },
    { key: "account_count", label: "Accounts", value: (s) => s.account_count },
    { key: "unlinked_count", label: "Unlinked", value: (s) => s.unlinked_count },
    {
      key: "last_sync",
      label: "Last sync",
      filter: "select",
      value: (s) => s.connector?.last_run_status ?? "never",
      render: (s) =>
        s.connector?.last_run_status ? (
          <Badge tone={syncTone(s.connector.last_run_status)}>{s.connector.last_run_status}</Badge>
        ) : (
          <span className="muted">never</span>
        ),
    },
    {
      key: "connector",
      label: "Connector",
      filter: "select",
      value: (s) =>
        isConnector(s) ? (s.connector?.configured ? "configured" : "not configured") : "upload only",
      render: (s) => connectorCell(s),
    },
    { key: "upload", label: "Upload", sortable: false, render: (s) => <UploadCell source={s} /> },
    { key: "bulk", label: "Bulk link", sortable: false, render: (s) => <BulkCell source={s} /> },
  ];

  function isConnector(s: Source) {
    return s.source_type === "ldap" || s.source_type === "entra" || s.source_type === "sql";
  }

  function connectorCell(s: Source) {
    if (!isConnector(s)) return <span className="muted">upload only</span>;
    return (
      <>
        {s.connector?.configured ? <Badge tone="ok">configured</Badge> : <Badge tone="neutral">not configured</Badge>}{" "}
        <button className="secondary" onClick={() => setSyncSource(s)}>
          Configure
        </button>{" "}
        <button className="secondary" onClick={() => void syncNow(s)} disabled={!s.connector?.configured}>
          Sync now
        </button>
      </>
    );
  }

  async function syncNow(s: Source) {
    try {
      const r = await api.sources.syncNow(s.id);
      setNotice(`Sync run #${r.run_id} enqueued for ${s.name}`);
      await loadSources();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => setCreating(true)}>Create source</button>
      </div>
      <Card title="Sources">
        {!sources ? (
          <p className="muted">Loading.</p>
        ) : sources.length === 0 ? (
          <p className="empty">No sources yet. Create one, then upload a CSV snapshot or configure a connector.</p>
        ) : (
          <DataTable viewKey="sources" columns={columns} rows={sources} getRowKey={(s) => s.id} searchable />
        )}
      </Card>
      {creating && (
        <CreateSourceModal
          onClose={() => setCreating(false)}
          onCreated={loadSources}
          setError={setError}
          setNotice={setNotice}
        />
      )}
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
        <Card title={`Accounts - source ${selected} (${accounts.total})`}>
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
                      "-"
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

function lookupIdentities(q: string): Promise<TypeaheadItem[]> {
  return api.identities.list({ q, page_size: 10 }).then((p) =>
    p.items.map((i) => ({
      id: i.id,
      label: [i.first_name, i.last_name].filter(Boolean).join(" ") || i.username || i.employee_id,
      value: i.employee_id,
      sub: i.employee_id + (i.department ? ` · ${i.department}` : ""),
    })),
  );
}

function CreateSourceModal({
  onClose,
  onCreated,
  setError,
  setNotice,
}: Msg & { onClose: () => void; onCreated: () => Promise<void> }) {
  const [name, setName] = useState("");
  const [type, setType] = useState("csv");
  const [owner, setOwner] = useState<TypeaheadItem | null>(null);
  const [ownerText, setOwnerText] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim()) return;
    if (ownerText.trim() && !owner) return; // unmatched owner text is blocked inline
    setBusy(true);
    try {
      await api.sources.create({
        name,
        source_type: type,
        owner_employee_id: owner?.value,
      });
      setNotice(`Source "${name}" created`);
      onClose();
      await onCreated();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Create source" onClose={onClose}>
      <div className="form-grid">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="App Directory" autoFocus />
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
          Owner (optional)
          <Typeahead
            lookup={lookupIdentities}
            onSelect={setOwner}
            onTextChange={setOwnerText}
            placeholder="Search name, username, or employee ID"
          />
          {ownerText.trim() && !owner && (
            <span className="error-text">
              Pick an owner from the list, or clear the field (unmatched IDs are rejected).
            </span>
          )}
        </label>
      </div>
      <p className="muted">The owner receives sync notices and review assignments for this source.</p>
      <div className="actions">
        <button onClick={() => void submit()} disabled={busy || !name.trim()}>
          {busy ? "Creating." : "Create"}
        </button>
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}

function UploadCell({ source }: { source: Source }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [lastMsg, setLastMsg] = useState("");
  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) {
      setLastMsg("Choose a file first");
      return;
    }
    try {
      const r = await api.sources.uploadCsv(source.id, file);
      setLastMsg(`+${r.accounts_created} acc / +${r.entitlements_created} ent`);
    } catch (e) {
      setLastMsg(errMsg(e));
    }
  }
  return (
    <>
      <input ref={fileRef} type="file" accept=".csv" />
      <button className="secondary" onClick={() => void upload()}>
        Upload
      </button>
      {lastMsg && <span className="muted"> {lastMsg}</span>}
    </>
  );
}

function BulkCell({ source }: { source: Source }) {
  const [msg, setMsg] = useState("");
  async function bulkLink(match: "username" | "email") {
    try {
      const r = await api.sources.bulkLink(source.id, match);
      setMsg(`${r.linked}/${r.considered}`);
    } catch (e) {
      setMsg(errMsg(e));
    }
  }
  return (
    <>
      <button className="secondary" onClick={() => void bulkLink("username")}>
        By username
      </button>{" "}
      <button className="secondary" onClick={() => void bulkLink("email")}>
        By email
      </button>
      {msg && <span className="muted"> {msg}</span>}
    </>
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
  const stored = source.connector?.config ?? {};
  const [config, setConfig] = useState<Record<string, string>>({ ...stored });
  const [secret, setSecret] = useState("");
  const [interval, setIntervalInput] = useState(
    source.connector?.interval_minutes != null ? String(source.connector.interval_minutes) : "",
  );
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
    <Modal title={`Connector - ${source.name} (${source.source_type})`} onClose={onClose} wide>
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
      <div className="actions">
        <button onClick={() => void save()} disabled={busy}>
          {busy ? "Validating." : "Validate & save"}
        </button>{" "}
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>{" "}
        <button className="secondary" onClick={() => setShowHistory(!showHistory)}>
          {showHistory ? "Hide history" : "Run history"}
        </button>
      </div>
      {showHistory && <RunHistory sourceId={source.id} setError={setError} />}
    </Modal>
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
    <Card title={`Sync runs - source ${sourceId}`}>
      {!runs ? (
        <p className="muted">Loading.</p>
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
                <td>{r.started_at ?? "-"}</td>
                <td>{r.finished_at ?? "-"}</td>
                <td>
                  {r.stats
                    ? `+${r.stats.accounts_created ?? 0} acc / ${r.stats.entitlements_created ?? 0} ent / miss ${r.stats.missing_from_snapshot ?? 0}`
                    : "-"}
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
