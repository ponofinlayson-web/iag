import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";
import { currentTheme, toggleTheme } from "../theme";
import { api } from "../api/client";
import { errMsg, Modal } from "./ui";

interface NavItem {
  to: string;
  label: string;
  roles: string[];
}

export const NAV: NavItem[] = [
  { to: "/", label: "Dashboard", roles: ["system_admin", "certification_admin", "reviewer", "auditor", "report_viewer"] },
  { to: "/identities", label: "Identities", roles: ["system_admin", "certification_admin"] },
  { to: "/sources", label: "Sources", roles: ["system_admin", "certification_admin"] },
  { to: "/entitlements", label: "Entitlements", roles: ["system_admin", "certification_admin"] },
  { to: "/campaigns", label: "Campaigns", roles: ["system_admin", "certification_admin"] },
  { to: "/risk", label: "Risk", roles: ["system_admin", "certification_admin", "auditor", "report_viewer"] },
  { to: "/sod", label: "SoD Rules", roles: ["system_admin", "certification_admin"] },
  { to: "/remediation", label: "Remediation", roles: ["system_admin", "certification_admin"] },
  { to: "/api-keys", label: "API Keys", roles: ["system_admin"] },
  { to: "/users", label: "Users", roles: ["system_admin"] },
  { to: "/outbox", label: "Reminders", roles: ["system_admin", "certification_admin"] },
  { to: "/reviews", label: "Reviews", roles: ["system_admin", "certification_admin", "reviewer"] },
  { to: "/audit", label: "Audit", roles: ["system_admin", "certification_admin", "auditor"] },
];

export default function Layout() {
  const { me, logout } = useAuth();
  const [light, setLight] = useState(currentTheme() === "light");
  const [pwOpen, setPwOpen] = useState(false);
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
              <button
                className="secondary theme-toggle"
                aria-label={light ? "Switch to dark theme" : "Switch to light theme"}
                title={light ? "Switch to dark theme" : "Switch to light theme"}
                onClick={() => setLight(toggleTheme() === "light")}
              >
                {light ? "🌙" : "☀"}
              </button>
              <span>
                {me.username} · {me.role}
              </span>
              {pwOpen && <ChangePassword onClose={() => setPwOpen(false)} />}
              <button className="secondary" onClick={() => setPwOpen(true)}>
                Change password
              </button>
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

function ChangePassword({ onClose }: { onClose: () => void }) {
  const { logout } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setError("");
    if (next !== confirm) {
      setError("New passwords do not match");
      return;
    }
    setBusy(true);
    try {
      await api.auth.changePassword(current, next);
      onClose();
      await logout();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Change password" onClose={onClose}>
      <div className="form-grid">
        <label>
          Current password
          <input
            type="password"
            autoFocus
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            autoComplete="current-password"
          />
        </label>
        <label>
          New password (min 8 characters)
          <input
            type="password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            autoComplete="new-password"
          />
        </label>
        <label>
          Confirm new password
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </label>
      </div>
      {error && <p className="error-text">{error}</p>}
      <p className="muted">Changing your password signs you out. Sign back in with the new one.</p>
      <div className="actions">
        <button onClick={() => void submit()} disabled={busy || !current || !next || !confirm}>
          {busy ? "Saving…" : "Change password"}
        </button>{" "}
        <button className="secondary" onClick={onClose}>
          Cancel
        </button>
      </div>
    </Modal>
  );
}
