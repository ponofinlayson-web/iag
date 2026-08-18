import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { OutboxRow } from "../api/client";
import { Badge, Card, Empty } from "../components/ui";

const STATUSES = ["pending", "sending", "sent", "failed", "cancelled"];

function statusTone(s: string): "ok" | "warn" | "bad" | "neutral" {
  if (s === "sent") return "ok";
  if (s === "failed") return "bad";
  if (s === "sending") return "warn";
  return "neutral";
}

export default function Outbox() {
  const [rows, setRows] = useState<OutboxRow[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [error, setError] = useState("");
  const pageSize = 50;

  function load() {
    const params: Record<string, string | number> = { page, page_size: pageSize };
    if (status) params.status = status;
    if (campaignId && !Number.isNaN(Number(campaignId))) params.campaign_id = Number(campaignId);
    api.reminders
      .outbox(params)
      .then((r) => {
        setRows(r.items);
        setTotal(r.total);
      })
      .catch((e) => setError(e.message));
  }

  useEffect(load, [page, status, campaignId]);

  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      <Card title="Reminder outbox">
        <p className="muted">
          One row per reviewer notified when a campaign starts. Workers inside the app replicas claim and
          send them; this view is read-only.
        </p>
        <div className="row" style={{ marginBottom: 8 }}>
          <input
            placeholder="Filter by campaign id"
            value={campaignId}
            onChange={(e) => {
              setPage(1);
              setCampaignId(e.target.value);
            }}
            style={{ width: 180 }}
          />
          <select
            value={status}
            onChange={(e) => {
              setPage(1);
              setStatus(e.target.value);
            }}
          >
            <option value="">All statuses</option>
            {STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </div>
        {rows === null ? (
          <p className="muted">Loading…</p>
        ) : rows.length === 0 ? (
          <Empty>No reminders queued</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Id</th>
                <th>Campaign</th>
                <th>Recipient</th>
                <th>Subject</th>
                <th>Status</th>
                <th>Attempts</th>
                <th>Due</th>
                <th>Sent</th>
                <th>Last error</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td>{r.id}</td>
                  <td>{r.campaign_id}</td>
                  <td>{r.recipient ?? "—"}</td>
                  <td>{r.subject}</td>
                  <td>
                    <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                  </td>
                  <td>{r.attempts}</td>
                  <td>{r.due_at ? new Date(r.due_at).toLocaleString() : "—"}</td>
                  <td>{r.sent_at ? new Date(r.sent_at).toLocaleString() : "—"}</td>
                  <td className="muted" title={r.last_error ?? ""}>
                    {r.last_error ? r.last_error.slice(0, 40) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <div className="row" style={{ marginTop: 8, alignItems: "center" }}>
          <button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
            Prev
          </button>
          <span className="muted">
            Page {page} / {pages} · {total} rows
          </span>
          <button disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
            Next
          </button>
        </div>
      </Card>
    </div>
  );
}
