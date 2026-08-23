import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Identity } from "../api/client";
import { Badge, Card, errMsg } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";

export default function Identities() {
  const [rows, setRows] = useState<Identity[] | null>(null);
  const [error, setError] = useState("");
  const [total, setTotal] = useState(0);

  // Plan non-goal: server-side pagination. Fetch a large page and let the
  // DataTable filter/sort client-side; revisit when identity counts grow.
  useEffect(() => {
    api.identities
      .list({ page_size: 10000 })
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch((e: unknown) => setError(errMsg(e)));
  }, []);

  const columns: Column<Identity>[] = [
    { key: "employee_id", label: "Employee ID", pinned: true, filter: "text" },
    {
      key: "last_name",
      label: "Name",
      pinned: true,
      filter: "text",
      value: (it) => [it.first_name, it.last_name].filter(Boolean).join(" "),
      render: (it) => (
        <>
          {it.first_name} {it.last_name}
        </>
      ),
    },
    { key: "username", label: "Username", filter: "text" },
    { key: "email", label: "Email", filter: "text" },
    { key: "department", label: "Department", filter: "select" },
    { key: "job_title", label: "Title", filter: "text" },
    {
      key: "is_active",
      label: "Status",
      filter: "select",
      value: (it) => (it.is_active ? "active" : "inactive"),
      render: (it) =>
        it.is_active ? <Badge tone="ok">active</Badge> : <Badge tone="neutral">inactive</Badge>,
    },
    { key: "source", label: "Source", filter: "select" },
  ];

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <Card title={`Identities (${total})`}>
        <div className="row" style={{ marginBottom: 12 }}>
          <span className="spacer" />
          <a href={api.identities.exportUrl()}>Export CSV</a>
        </div>
        {!rows ? (
          <p className="muted">Loading.</p>
        ) : rows.length === 0 ? (
          <p className="empty">No identities yet. Upload a snapshot or run a sync to populate.</p>
        ) : (
          <DataTable viewKey="identities" columns={columns} rows={rows} getRowKey={(it) => it.id} searchable />
        )}
      </Card>
    </div>
  );
}
