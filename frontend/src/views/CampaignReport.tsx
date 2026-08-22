import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { CampaignReport as Report } from "../api/client";
import { Badge, errMsg, statusTone } from "../components/ui";

export default function CampaignReport() {
  const { id } = useParams();
  const cid = Number(id);
  const [rep, setRep] = useState<Report | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.campaigns
      .report(cid)
      .then(setRep)
      .catch((e) => setError(errMsg(e)));
  }, [cid]);

  if (error) return <p className="error-text">{error}</p>;
  if (!rep) return <p className="muted">Loading…</p>;

  const c = rep.campaign;
  const d = rep.decisions;
  const wl = rep.reviewer_workload;

  return (
    <div className="report">
      <div className="report-actions no-print">
        <Link className="btn-secondary" to={`/campaigns/${cid}`}>
          ← Back to campaign
        </Link>
        <a className="btn-secondary" href={api.campaigns.reportCsvUrl(cid)}>
          Download CSV
        </a>
        <button onClick={() => window.print()}>Print / Save as PDF</button>
      </div>

      <header className="report-header">
        <h1>Certification Report — {c.name}</h1>
        <p className="muted">
          #{c.id} · status <Badge tone={statusTone(c.status)}>{c.status}</Badge> · mode {c.review_mode}
          {c.deadline ? ` · deadline ${c.deadline.slice(0, 10)}` : ""}
          {c.created_at ? ` · created ${c.created_at.slice(0, 10)}` : ""}
        </p>
        {c.description && <p>{c.description}</p>}
        <p className="muted">Generated {rep.generated_at.replace("T", " ").slice(0, 19)} UTC</p>
      </header>

      <section>
        <h2>Completion</h2>
        <p>
          {rep.completion.completed}/{rep.completion.total} decisions made ({rep.completion.progress_pct}%) ·{" "}
          {rep.completion.pending} outstanding
        </p>
        <p className="muted">
          approved {d.approved ?? 0} · revoked {d.revoked ?? 0} · pending {d.pending ?? 0} · in progress{" "}
          {d.in_progress ?? 0}
        </p>
      </section>

      <section>
        <h2>Reviewer workload</h2>
        {wl.length === 0 ? (
          <p className="muted">No reviews generated for this campaign.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Reviewer</th>
                <th>Assigned</th>
                <th>Approved</th>
                <th>Revoked</th>
                <th>Pending</th>
              </tr>
            </thead>
            <tbody>
              {wl.map((w) => (
                <tr key={w.reviewer}>
                  <td>{w.reviewer}</td>
                  <td>{w.assigned}</td>
                  <td>{w.approved}</td>
                  <td>{w.revoked}</td>
                  <td>{w.pending}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2>Revocations ({rep.revocations.length})</h2>
        {rep.revocations.length === 0 ? (
          <p className="muted">No access was revoked in this campaign.</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Identity</th>
                <th>Employee</th>
                <th>Source</th>
                <th>Entitlement</th>
                <th>Account</th>
                <th>Decided</th>
                <th>Reviewer</th>
                <th>Comment</th>
              </tr>
            </thead>
            <tbody>
              {rep.revocations.map((r, i) => (
                <tr key={i}>
                  <td>{r.identity ?? "—"}</td>
                  <td className="mono">{r.employee_id ?? "—"}</td>
                  <td>{r.source ?? "—"}</td>
                  <td>{r.entitlement ?? "—"}</td>
                  <td className="mono">{r.account ?? "—"}</td>
                  <td>{r.decided_at?.slice(0, 19).replace("T", " ") ?? "—"}</td>
                  <td>{r.reviewer ?? "—"}</td>
                  <td>{r.comment ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {rep.risk && (
        <section>
          <h2>Risk snapshot</h2>
          <p>
            From risk run {rep.risk.run_id.slice(0, 8)}… covering {rep.risk.scored_in_campaign} of this campaign’s
            identities:{" "}
            {Object.entries(rep.risk.band_distribution)
              .map(([b, n]) => `${n} ${b}`)
              .join(", ") || "none scored"}
          </p>
        </section>
      )}
    </div>
  );
}
