import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

interface NavItem {
  to: string;
  label: string;
  roles: string[];
}

const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", roles: ["system_admin", "certification_admin", "reviewer", "auditor", "report_viewer"] },
  { to: "/identities", label: "Identities", roles: ["system_admin", "certification_admin"] },
  { to: "/sources", label: "Sources", roles: ["system_admin", "certification_admin"] },
  { to: "/entitlements", label: "Entitlements", roles: ["system_admin", "certification_admin"] },
  { to: "/campaigns", label: "Campaigns", roles: ["system_admin", "certification_admin"] },
  { to: "/sod", label: "SoD Rules", roles: ["system_admin", "certification_admin"] },
  { to: "/reviews", label: "Reviews", roles: ["system_admin", "certification_admin", "reviewer"] },
  { to: "/audit", label: "Audit", roles: ["system_admin", "certification_admin", "auditor"] },
];

export default function Layout() {
  const { me, logout } = useAuth();
  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">IAG</div>
        <nav className="nav">
          {NAV.filter((n) => me && n.roles.includes(me.role)).map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "navlink active" : "navlink")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="userbox">
          {me && (
            <>
              <span>
                {me.username} · {me.role}
              </span>
              <button onClick={() => void logout()}>Logout</button>
            </>
          )}
        </div>
      </header>
      <main>
        <Outlet />
      </main>
    </div>
  );
}
