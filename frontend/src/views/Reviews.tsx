import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { ReviewQueueItem, ReviewHistoryItem } from "../api/client";
import { Badge, Card, statusTone, Modal } from "../components/ui";

export default function Reviews() {
  const [queue, setQueue] = useState<{ total: number; items: ReviewQueueItem[] } | null>(null);
  const [history, setHistory] = useState<{ items: ReviewHistoryItem[] } | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [revoke, setRevoke] = useState<{ ids: number[] } | null>(null);
  const [comment, setComment] = useState("");

  function load() {
    api.reviews.queue().then(setQueue).catch((e) => setError(e.message));
    api.reviews.history().then(setHistory).catch(() => undefined);
  }

  useEffect(load, []);

  function toggle(id: number) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  function openRevoke(ids: number[]) {
    setComment("");
    setError("");
    setRevoke({ ids });
  }

  async function confirmRevoke() {
    if (!revoke) return;
    const comments = comment.trim();
    if (!comments) {
      setError("Revocation requires a comment");
      return;
    }
    try {
      if (revoke.ids.length === 1) {
        await api.reviews.submit(revoke.ids[0], "revoke", comments);
        setNotice(`Review #${revoke.ids[0]} revoked`);
      } else {
        const r = await api.reviews.bulkSubmit(revoke.ids, "revoke", comments);
        setNotice(`Bulk revoke: ${r.submitted} submitted`);
      }
      setRevoke(null);
      setSelected(new Set());
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function submitOne(id: number, decision: "approve" | "revoke") {
    if (decision === "revoke") {
      openRevoke([id]);
      return;
    }
    try {
      await api.reviews.submit(id, "approve");
      setNotice(`Review #${id} approved`);
      setSelected(new Set());
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  async function submitBulk(decision: "approve" | "revoke") {
    if (selected.size === 0) return;
    if (decision === "revoke") {
      openRevoke([...selected]);
      return;
    }
    try {
      const r = await api.reviews.bulkSubmit([...selected], "approve");
      setNotice(`Bulk approve: ${r.submitted} submitted`);
      setSelected(new Set());
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <ReviewsTable queue={queue} selected={selected} toggle={toggle} submitOne={submitOne} submitBulk={submitBulk} />
      {history && (
        <Card title={`My history (${history.items.length})`}>
          <table>
            <thead>
              <tr>
                <th>Review</th>
                <th>Campaign</th>
                <th>Account</th>
                <th>Decision</th>
                <th>Completed</th>
              </tr>
            </thead>
            <tbody>
              {history.items.map((h) => (
                <tr key={h.id}>
                  <td>#{h.id}</td>
                  <td>{h.campaign_name}</td>
                  <td>{h.account_value}</td>
                  <td>{h.decision}</td>
                  <td>{h.completed_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {revoke && (
        <Modal
          title={
            revoke.ids.length === 1
              ? `Revoke review #${revoke.ids[0]}`
              : `Revoke ${revoke.ids.length} reviews`
          }
          onClose={() => setRevoke(null)}
        >
          <p className="muted">
            A comment is required so the decision and any remediation carry context.
          </p>
          <textarea
            autoFocus
            rows={3}
            style={{ width: "100%" }}
            placeholder="Why is this access being revoked?"
            value={comment}
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="actions">
            <button className="danger" onClick={() => void confirmRevoke()}>
              Submit revocation
            </button>
            <button className="secondary" onClick={() => setRevoke(null)}>
              Cancel
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}

function ReviewsTable({
  queue,
  selected,
  toggle,
  submitOne,
  submitBulk,
}: {
  queue: { total: number; items: ReviewQueueItem[] } | null;
  selected: Set<number>;
  toggle: (id: number) => void;
  submitOne: (id: number, decision: "approve" | "revoke") => Promise<void>;
  submitBulk: (decision: "approve" | "revoke") => Promise<void>;
}) {
  return (
    <Card title={`My review queue (${queue?.total ?? "…"})`}>
      {!queue ? (
        <p className="muted">Loading…</p>
      ) : queue.items.length === 0 ? (
        <p className="empty">Queue empty — nothing awaiting your decision.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th />
              <th>Review</th>
              <th>Campaign</th>
              <th>Account</th>
              <th>Privilege</th>
              <th>Status</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {queue.items.map((r) => (
              <tr key={r.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selected.has(r.id)}
                    onChange={() => toggle(r.id)}
                  />
                </td>
                <td>#{r.id}</td>
                <td>{r.campaign_name}</td>
                <td>{r.account_value}</td>
                <td>{r.privilege_level ?? "—"}</td>
                <td>
                  <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                </td>
                <td className="actions">
                  <button onClick={() => void submitOne(r.id, "approve")}>Approve</button>
                  <button className="danger" onClick={() => void submitOne(r.id, "revoke")}>
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {selected.size > 0 && (
        <div className="row" style={{ marginTop: 12 }}>
          <span className="muted">{selected.size} selected</span>
          <button onClick={() => void submitBulk("approve")}>Bulk approve</button>
          <button className="danger" onClick={() => void submitBulk("revoke")}>
            Bulk revoke
          </button>
        </div>
      )}
    </Card>
  );
}
