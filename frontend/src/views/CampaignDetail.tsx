import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CampaignDetail as CD } from "../api/client";
import { Badge, Card, errMsg, statusTone } from "../components/ui";

interface Preview {
  total_in_scope: number;
  will_create: number;
  skipped: Array<{ account_id: number; account_value: string; reason: string }>;
  sample: Array<{ account_id: number; reviewer: string }>;
}

interface Metrics {
  status: string;
  total: number;
  completed: number;
  progress_pct: number;
  by_status: Record<string, number>;
}

export default function CampaignDetail() {
  const { id } = useParams();
  const cid = Number(id);
  const nav = useNavigate();
  const [camp, setCamp] = useState<CD | null>(null);
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function load() {
    try {
      setCamp(await api.campaigns.get(cid));
      setMetrics(await api.campaigns.metrics(cid));
    } catch (e) {
      setError(errMsg(e));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cid]);

  async function act(label: string, fn: () => Promise<unknown>) {
    try {
      await fn();
      setNotice(`${label} ok`);
      setPreview(null);
      await load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function runPreview() {
    try {
      setPreview(await api.campaigns.preview(cid));
      setNotice("");
    } catch (e) {
      setError(errMsg(e));
    }
  }

  if (!camp) return <p className="muted">{error ? <span className="error-text">{error}</span> : "Loading…"}</p>;

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <p>
        <button className="secondary" onClick={() => nav("/campaigns")}>
          ← Back to campaigns
        </button>
      </p>
      <Card title={`Campaign #${camp.id} — ${camp.name}`}>
        <p>
          <Badge tone={statusTone(camp.status)}>{camp.status}</Badge> · mode {camp.review_mode}
          {camp.deadline ? ` · deadline ${camp.deadline.slice(0, 10)}` : ""}
        </p>
        {camp.description && <p className="muted">{camp.description}</p>}
        {metrics && (
          <p>
            {metrics.completed}/{metrics.total} reviews completed ({metrics.progress_pct}%)
          </p>
        )}
        <div className="row">
          {camp.status === "draft" && (
            <>
              <button className="secondary" onClick={() => void runPreview()}>
                Preview (DRY-RUN)
              </button>
              <button onClick={() => void act("Stage", () => api.campaigns.stage(cid))}>Stage</button>
            </>
          )}
          {camp.status === "staged" && (
            <button onClick={() => void act("Start", () => api.campaigns.start(cid))}>Start</button>
          )}
          {(camp.status === "staged" || camp.status === "active") && (
            <button className="danger" onClick={() => void act("Cancel", () => api.campaigns.cancel(cid))}>
              Cancel
            </button>
          )}
        </div>
      </Card>
      {preview && (
        <Card title={`DRY-RUN preview — ${preview.will_create} of ${preview.total_in_scope} in scope`}>
          {preview.skipped.length > 0 ? (
            <table>
              <thead>
                <tr>
                  <th>Account</th>
                  <th>Reason skipped</th>
                </tr>
              </thead>
              <tbody>
                {preview.skipped.map((s) => (
                  <tr key={s.account_id}>
                    <td>{s.account_value}</td>
                    <td className="muted">{s.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="empty">All in-scope accounts will get a review. No skips.</p>
          )}
          {preview.sample.length > 0 && (
            <p className="muted">Sample reviewers: {preview.sample.map((s) => s.reviewer).slice(0, 8).join(", ")}</p>
          )}
        </Card>
      )}
    </div>
  );
}
