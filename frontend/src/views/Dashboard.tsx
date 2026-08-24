import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { DashboardData } from "../api/client";
import { Card, Stat, errMsg } from "../components/ui";

export default function Dashboard() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.dashboard
      .get()
      .then(setData)
      .catch((e: unknown) => setError(errMsg(e)));
  }, []);

  if (error) return <p className="error-text">{error}</p>;
  if (!data) return <p className="muted">Loading…</p>;

  return (
    <div>
      <Card title="Portfolio">
        <div className="stat-row">
          <Stat label="Identities" value={data.identities} />
          <Stat label="Accounts" value={data.accounts} />
          <Stat label="Unlinked accounts" value={data.unlinked_accounts} tone={data.unlinked_accounts > 0 ? "warn" : undefined} />
          <Stat label="Privileged accounts" value={data.privileged_accounts} tone={data.privileged_accounts > 0 ? "warn" : undefined} />
          <Stat label="Active campaigns" value={data.active_campaigns} tone={data.active_campaigns > 0 ? "ok" : undefined} />
        </div>
      </Card>
      <Card title="My workload">
        <div className="stat-row">
          <Stat label="Pending reviews" value={data.my_pending_reviews} tone={data.my_pending_reviews > 0 ? "warn" : "ok"} />
        </div>
      </Card>
    </div>
  );
}
