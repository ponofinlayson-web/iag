import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Campaign } from "../api/client";
import { Badge, Card, statusTone } from "../components/ui";

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const navigate = useNavigate();

  async function load() {
    try {
      setCampaigns((await api.campaigns.list()).items);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <Card title="Campaigns">
        {!campaigns ? (
          <p className="muted">Loading…</p>
        ) : campaigns.length === 0 ? (
          <p className="empty">No campaigns. Create one below.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Status</th>
                <th>Mode</th>
                <th>Pending</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {campaigns.map((c) => (
                <tr key={c.id}>
                  <td>{c.id}</td>
                  <td>
                    <a onClick={() => navigate(`/campaigns/${c.id}`)} style={{ cursor: "pointer" }}>
                      {c.name}
                    </a>
                  </td>
                  <td>
                    <Badge tone={statusTone(c.status)}>{c.status}</Badge>
                  </td>
                  <td>{c.review_mode}</td>
                  <td>{c.pending_reviews}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <NewCampaign onCreate={load} setError={setError} setNotice={setNotice} />
    </div>
  );
}

function NewCampaign({ onCreate, setError, setNotice }: { onCreate: () => Promise<void>; setError: (s: string) => void; setNotice: (s: string) => void }) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState("source_owner");

  async function submit() {
    if (!name.trim()) return;
    try {
      const r = await api.campaigns.create({ name, review_mode: mode });
      setNotice(`Campaign created (id ${r.id})`);
      setName("");
      await onCreate();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Card title="New campaign">
      <div className="form-grid">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Q1 Access Review" />
        </label>
        <label>
          Reviewer mode
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="source_owner">source_owner</option>
            <option value="manager">manager</option>
          </select>
        </label>
      </div>
      <button onClick={() => void submit()}>Create</button>
    </Card>
  );
}
