import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Campaign } from "../api/client";
import { Badge, Card, errMsg, Modal, statusTone } from "../components/ui";
import { DataTable, type Column } from "../components/DataTable";

export default function Campaigns() {
  const [campaigns, setCampaigns] = useState<Campaign[] | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const navigate = useNavigate();

  async function load() {
    try {
      setCampaigns((await api.campaigns.list()).items);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  const columns: Column<Campaign>[] = [
    { key: "id", label: "ID", pinned: true, sortable: false, value: (c) => c.id },
    {
      key: "name",
      label: "Name",
      pinned: true,
      filter: "text",
      render: (c) => (
        <a onClick={() => navigate(`/campaigns/${c.id}`)} style={{ cursor: "pointer" }}>
          {c.name}
        </a>
      ),
    },
    {
      key: "status",
      label: "Status",
      filter: "select",
      render: (c) => <Badge tone={statusTone(c.status)}>{c.status}</Badge>,
    },
    { key: "review_mode", label: "Mode", filter: "select" },
    { key: "pending_reviews", label: "Pending", value: (c) => c.pending_reviews },
    { key: "deadline", label: "Deadline", value: (c) => c.deadline ?? "—" },
  ];

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      <div className="row" style={{ marginBottom: 12 }}>
        <button onClick={() => setCreating(true)}>Create campaign</button>
      </div>
      <Card title="Campaigns">
        {!campaigns ? (
          <p className="muted">Loading.</p>
        ) : campaigns.length === 0 ? (
          <p className="empty">No campaigns. Create one to start a review cycle.</p>
        ) : (
          <DataTable viewKey="campaigns" columns={columns} rows={campaigns} getRowKey={(c) => c.id} searchable />
        )}
      </Card>
      {creating && <CreateCampaignModal onClose={() => setCreating(false)} onCreated={load} setError={setError} setNotice={setNotice} />}
    </div>
  );
}

function CreateCampaignModal({
  onClose,
  onCreated,
  setError,
  setNotice,
}: {
  onClose: () => void;
  onCreated: () => Promise<void>;
  setError: (s: string) => void;
  setNotice: (s: string) => void;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState("source_owner");
  const [description, setDescription] = useState("");
  const [deadline, setDeadline] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    if (!name.trim()) return;
    setBusy(true);
    try {
      const r = await api.campaigns.create({
        name,
        review_mode: mode,
        description: description || undefined,
        deadline: deadline || undefined,
      });
      setNotice(`Campaign created (id ${r.id})`);
      onClose();
      await onCreated();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Create campaign" onClose={onClose}>
      <div className="form-grid">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Q1 Access Review" autoFocus />
        </label>
        <label>
          Reviewer mode
          <select value={mode} onChange={(e) => setMode(e.target.value)}>
            <option value="source_owner">source_owner</option>
            <option value="manager">manager</option>
          </select>
        </label>
        <label>
          Description (optional)
          <input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What this cycle covers" />
        </label>
        <label>
          Deadline (optional)
          <input
            type="date"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
          />
        </label>
      </div>
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
