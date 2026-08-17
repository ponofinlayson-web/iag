import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Identity } from "../api/client";
import { Card, errMsg } from "../components/ui";

export default function Identities() {
  const [data, setData] = useState<{ total: number; items: Identity[] } | null>(null);
  const [q, setQ] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const pageSize = 25;

  useEffect(() => {
    const t = setTimeout(() => {
      api.identities
        .list({ q, page, page_size: pageSize })
        .then(setData)
        .catch((e: unknown) => setError(errMsg(e)));
    }, 250);
    return () => clearTimeout(t);
  }, [q, page]);

  return (
    <div>
      <Card title={`Identities${data ? ` (${data.total})` : ""}`}>
        <div className="row" style={{ marginBottom: 12 }}>
          <input
            placeholder="Search employee id, username, email, last name…"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
            style={{ flex: 1 }}
          />
          <a href={api.identities.exportUrl()}>Export CSV</a>
        </div>
        {error && <p className="error-text">{error}</p>}
        {data && (
          <table>
            <thead>
              <tr>
                <th>Employee ID</th>
                <th>Name</th>
                <th>Username</th>
                <th>Email</th>
                <th>Department</th>
                <th>Title</th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((it) => (
                <tr key={it.id}>
                  <td>{it.employee_id}</td>
                  <td>
                    {it.first_name} {it.last_name}
                  </td>
                  <td>{it.username}</td>
                  <td>{it.email}</td>
                  <td>{it.department}</td>
                  <td>{it.job_title}</td>
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
