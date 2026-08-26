import { useState } from "react";
import { useAuth } from "../auth";
import { api } from "../api/client";
import { errMsg } from "../components/ui";

/**
 * Full-page forced password change. Rendered by App INSTEAD of the shell
 * when me.must_change_password is set — no nav, no routes, logout is the
 * only way out besides completing the change.
 */
export default function ForcedPasswordChange() {
  const { me, refresh, logout } = useAuth();
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
      await refresh();
    } catch (e) {
      setError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-box">
      <h1>Change your password</h1>
      <p className="muted">
        {me?.username} — your password was set or reset by an administrator and must be changed
        before you can continue.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
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
        {error && <p className="error-text">{error}</p>}
        <button type="submit" disabled={busy || !current || !next || !confirm}>
          {busy ? "Saving…" : "Set new password"}
        </button>{" "}
        <button type="button" className="secondary" onClick={() => void logout()}>
          Log out instead
        </button>
      </form>
    </div>
  );
}
