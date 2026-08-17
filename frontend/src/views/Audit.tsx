import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { AuditEntryView, ChainStatus, Paged } from "../api/client";
import { Card, errMsg } from "../components/ui";

export default function Audit() {
  const [data, setData] = useState<Paged<AuditEntryView> | null>(null);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const pageSize = 25;

  useEffect(() => {
    api.audit
      .list({ action, page, page_size: pageSize })
      .then(setData)
      .catch((e: unknown) => setError(errMsg(e)));
    api.audit.verify().then(setChain).catch(() => undefined);
  }, [action, page]);

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <Card title="Hash chain">
        {chain === null ? (
          <p className="muted">Verifying…</p>
        ) : chain.valid ? (
          <p className="ok-text">
            Chain valid — {chain.entries} entries, head {chain.head?.slice(0, 16)}…
          </p>
        ) : (
          <p className="error-text">
            CHAIN BROKEN at entry {chain.broken_at} — {chain.reason}
          </p>
        )}
        <div className="row" style={{ marginTop: 8 }}>
          <a href={api.audit.exportUrl()}>Export CSV</a>
        </div>
      </Card>
      <Card title={`Audit log${data ? ` (${data.total})` : ""}`}>
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            placeholder="Filter by action"
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
            style={{ flex: 1 }}
          />
        </div>
        {data && (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Timestamp</th>
                <th>Actor</th>
                <th>Action</th>
                <th>Entity</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((e) => (
                <tr key={e.id}>
                  <td>{e.id}</td>
                  <td>{e.ts?.slice(0, 19).replace("T", " ")}</td>
                  <td>{e.actor_username}</td>
                  <td>{e.action}</td>
                  <td>{e.entity_type}:{e.entity_id}</td>
                  <td className="muted">{e.details}</td>
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
