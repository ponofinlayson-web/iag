import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Entitlement } from "../api/client";
import { Card, errMsg } from "../components/ui";

const PRIVILEGES = ["low", "moderate", "high", "very_high"];

export default function Entitlements() {
  const [data, setData] = useState<{ total: number; items: Entitlement[] } | null>(null);
  const [stats, setStats] = useState<{ total: number; classified: number; unclassified: number; by_level: Record<string, number> } | null>(null);
  const [q, setQ] = useState("");
  const [privilege, setPrivilege] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const pageSize = 25;

  function load() {
    api.entitlements
      .list({ q, privilege, page, page_size: pageSize })
      .then(setData)
      .catch((e) => setError(e.message));
    api.entitlements.stats().then(setStats).catch(() => undefined);
  }

  useEffect(load, [q, privilege, page]);

  async function setLevel(id: number, level: string) {
    try {
      await api.entitlements.setPrivilege(id, level);
      setNotice(`Privilege set to ${level}`);
      load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      {stats && (
        <Card title="Catalog stats">
          <div className="stat-row">
            <span className="stat">
              <div className="stat-value">{stats.total}</div>
              <div className="stat-label">Total</div>
            </span>
            <span className="stat">
              <div className="stat-value">{stats.classified}</div>
              <div className="stat-label">Classified</div>
            </span>
            <span className="stat">
              <div className="stat-value">{stats.unclassified}</div>
              <div className="stat-label">Unclassified</div>
            </span>
          </div>
        </Card>
      )}
      <Card title={`Entitlements${data ? ` (${data.total})` : ""}`}>
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            placeholder="Search name…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            style={{ flex: 1 }}
          />
          <select value={privilege} onChange={(e) => { setPrivilege(e.target.value); setPage(1); }}>
            <option value="">All privilege levels</option>
            {PRIVILEGES.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        {data && (
          <table>
            <thead>
              <tr>
                <th>Catalog ID</th>
                <th>Name</th>
                <th>Privilege</th>
                <th>Source</th>
                <th>Last seen</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id}>
                  <td>{e.catalog_id}</td>
                  <td>{e.name}</td>
                  <td>
                    <select value={e.privilege_level ?? ""} onChange={(ev) => void setLevel(e.id, ev.target.value)}>
                      <option value="">— classify —</option>
                      {PRIVILEGES.map((p) => (
                        <option key={p} value={p}>
                          {p}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>#{e.source_id}</td>
                  <td>{e.last_seen_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="pager">
          <button className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Prev
          </button>
          <span>
            Page {page}
            {data ? ` of ${Math.max(1, Math.ceil(data.total / pageSize))}` : ""}
          </span>
          <button
            className="secondary"
            disabled={!data || page >= Math.ceil(data.total / pageSize)}
            onClick={() => setPage((p) => p + 1)}
          >
            Next
          </button>
        </div>
      </Card>
    </div>
  );
}
