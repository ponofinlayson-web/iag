import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import Login from "./views/Login";
import Dashboard from "./views/Dashboard";
import Identities from "./views/Identities";
import Sources from "./views/Sources";
import Entitlements from "./views/Entitlements";
import Campaigns from "./views/Campaigns";
import CampaignDetail from "./views/CampaignDetail";
import Reviews from "./views/Reviews";
import Audit from "./views/Audit";
import SodRules from "./views/SodRules";
import Remediation from "./views/Remediation";
import ApiKeys from "./views/ApiKeys";
import Outbox from "./views/Outbox";

export default function App() {
  const { me, loading } = useAuth();
  if (loading) {
    return <div className="center-screen">Loading…</div>;
  }
  if (!me) {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    );
  }
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Dashboard />} />
        <Route path="/identities" element={<Identities />} />
        <Route path="/sources" element={<Sources />} />
        <Route path="/entitlements" element={<Entitlements />} />
        <Route path="/campaigns" element={<Campaigns />} />
        <Route path="/campaigns/:id" element={<CampaignDetail />} />
        <Route path="/sod" element={<SodRules />} />
        <Route path="/remediation" element={<Remediation />} />
      <Route path="/api-keys" element={<ApiKeys />} />
        <Route path="/outbox" element={<Outbox />} />
        <Route path="/reviews" element={<Reviews />} />
        <Route path="/audit" element={<Audit />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
