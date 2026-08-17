import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Account, Source } from "../api/client";
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

  async function loadSources() {
    try {
      setSources((await api.sources.list()).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
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
          <p className="empty">No sources yet. Create one above, then upload a CSV snapshot.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Type</th>
                <th>Accounts</th>
                <th>Unlinked</th>
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
                />
              ))}
            </tbody>
          </table>
        )}
      </Card>
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
      setError(e instanceof Error ? e.message : String(e));
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
            <option value="csv">csv</option>
            <option value="xlsx">xlsx</option>
            <option value="ldap">ldap (stubbed)</option>
            <option value="entra">entra (stubbed)</option>
            <option value="sql">sql (stubbed)</option>
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
}: Msg & { source: Source; reload: () => Promise<void>; onSelect: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  async function upload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;
    try {
      const r = await api.sources.uploadCsv(source.id, file);
      setNotice(`Uploaded to ${source.name}: ${r.accounts_created} accounts, ${r.entitlements_created} entitlements`);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  async function bulkLink(match: "username" | "email") {
    try {
      const r = await api.sources.bulkLink(source.id, match);
      setNotice(`Bulk linked ${r.linked}/${r.considered} by ${match}`);
      await reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
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
