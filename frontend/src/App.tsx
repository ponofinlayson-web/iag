import { Navigate, Route, Routes, matchPath, useLocation } from "react-router-dom";
import type { ReactNode } from "react";
import { useAuth } from "./auth";
import Layout from "./components/Layout";
import { NAV } from "./components/Layout";
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
import Users from "./views/Users";
import Outbox from "./views/Outbox";
import Risk from "./views/Risk";
import CampaignReport from "./views/CampaignReport";
import ForcedPasswordChange from "./views/ForcedPasswordChange";

/**
 * Route role gates mirror the backend require_roles sets; NAV roles are
 * the same source the topbar filters on. The backend stays the security
 * boundary — this stops the app shell from rendering around a view the
 * API will 403 anyway (direct URL entry).
 */
const navRoles: Record<string, string[]> = Object.fromEntries(
  NAV.map((n) => [n.to, n.roles] as const),
);
const REPORT_VIEWERS = ["system_admin", "certification_admin", "auditor", "report_viewer"];

const ROUTES: { path: string; roles: string[]; element: ReactNode }[] = [
  { path: "/", roles: navRoles["/"], element: <Dashboard /> },
  { path: "/identities", roles: navRoles["/identities"], element: <Identities /> },
  { path: "/sources", roles: navRoles["/sources"], element: <Sources /> },
  { path: "/entitlements", roles: navRoles["/entitlements"], element: <Entitlements /> },
  { path: "/campaigns", roles: navRoles["/campaigns"], element: <Campaigns /> },
  { path: "/campaigns/:id", roles: REPORT_VIEWERS, element: <CampaignDetail /> },
  { path: "/campaigns/:id/report", roles: REPORT_VIEWERS, element: <CampaignReport /> },
  { path: "/risk", roles: navRoles["/risk"], element: <Risk /> },
  { path: "/sod", roles: navRoles["/sod"], element: <SodRules /> },
  { path: "/remediation", roles: navRoles["/remediation"], element: <Remediation /> },
  { path: "/api-keys", roles: navRoles["/api-keys"], element: <ApiKeys /> },
  { path: "/users", roles: navRoles["/users"], element: <Users /> },
  { path: "/outbox", roles: navRoles["/outbox"], element: <Outbox /> },
  { path: "/reviews", roles: navRoles["/reviews"], element: <Reviews /> },
  { path: "/audit", roles: navRoles["/audit"], element: <Audit /> },
];

function Forbidden() {
  return (
    <div className="login-box">
      <h1>403 — Forbidden</h1>
      <p className="muted">You do not have a role that can open this page.</p>
      <p>
        <a href="/">Go to dashboard</a>
      </p>
    </div>
  );
}

export default function App() {
  const { me, loading } = useAuth();
  const { pathname } = useLocation();
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
  if (me.must_change_password) {
    return <ForcedPasswordChange />;
  }
  const matched = ROUTES.find((r) => matchPath(r.path, pathname));
  if (matched && !matched.roles.includes(me.role)) {
    return <Forbidden />;
  }
  return (
    <Routes>
      <Route element={<Layout />}>
        {ROUTES.map(({ path, element }) => (
          <Route key={path} path={path} element={element} />
        ))}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Route>
    </Routes>
  );
}
