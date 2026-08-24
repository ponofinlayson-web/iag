import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { RiskSnapshotRow, RiskSummary, RiskTrendPoint } from "../api/client";
import { Badge, Card, Empty, errMsg, Stat } from "../components/ui";
import { useAuth } from "../auth";

function bandTone(band: string): "ok" | "warn" | "bad" | "neutral" {
  switch (band) {
    case "critical":
      return "bad";
    case "high":
      return "warn";
    case "medium":
      return "warn";
    default:
      return "neutral";
  }
}

function Sparkline({ points }: { points: RiskTrendPoint[] }) {
  if (points.length === 0) return <span className="muted">no history</span>;
  const scores = points.map((p) => p.score);
  const w = 160;
  const h = 36;
  const max = Math.max(...scores, 1);
  const step = points.length > 1 ? w / (points.length - 1) : w;
  const path = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${i * step},${h - (p.score / max) * (h - 4) - 2}`)
    .join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="sparkline" role="img" aria-label="score trend">
      <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function TrendPanel({ identityId, onClose }: { identityId: number; onClose: () => void }) {
  const [points, setPoints] = useState<RiskTrendPoint[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.risk
      .trend(identityId)
      .then((r) => setPoints(r.items))
      .catch((e) => setError(errMsg(e)));
  }, [identityId]);
  return (
    <Card title={`Score trend — identity #${identityId}`}>
      {error && <p className="error-text">{error}</p>}
      {!points ? (
        <p className="muted">Loading…</p>
      ) : points.length === 0 ? (
        <Empty>No snapshots for this identity.</Empty>
      ) : (
        <div>
          <Sparkline points={points} />
          <table>
            <thead>
              <tr>
                <th>Run</th>
                <th>Score</th>
                <th>Band</th>
                <th>Computed</th>
              </tr>
            </thead>
            <tbody>
              {points.map((p) => (
                <tr key={p.run_id}>
                  <td className="mono muted">{p.run_id.slice(0, 8)}…</td>
                  <td>{p.score}</td>
                  <td>
                    <Badge tone={bandTone(p.band)}>{p.band}</Badge>
                  </td>
                  <td>{p.computed_at?.slice(0, 19).replace("T", " ")}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p>
        <button className="secondary" onClick={onClose}>
          Close
        </button>
      </p>
    </Card>
  );
}

export default function Risk() {
  const { me } = useAuth();
  const canRun = me?.role === "system_admin" || me?.role === "certification_admin";
  const [summary, setSummary] = useState<RiskSummary | null>(null);
  const [rows, setRows] = useState<RiskSnapshotRow[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [band, setBand] = useState("");
  const [department, setDepartment] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [trendId, setTrendId] = useState<number | null>(null);

  async function loadSnapshots(p = 1, b = band, d = department) {
    try {
      const r = await api.risk.snapshots({ band: b, department: d, page: p, page_size: 50 });
      setRows(r.items);
      setTotal(r.total);
      setPage(p);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  async function load() {
    try {
      setSummary(await api.risk.summary());
      await loadSnapshots(1);
    } catch (e) {
      setError(errMsg(e));
    }
  }

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function computeNow() {
    setError("");
    try {
      const r = await api.risk.run();
      setNotice(`Run ${r.run_id.slice(0, 8)}… scored ${r.scored_identities} identities (avg ${r.average_score})`);
      await load();
    } catch (e) {
      setError(errMsg(e));
    }
  }

  const bands = summary?.band_distribution ?? {};
  const pages = Math.max(1, Math.ceil(total / 50));

  return (
    <div>
      {error && <p className="error-text">{error}</p>}
      {notice && <p className="ok-text">{notice}</p>}
      {summary && (
        <Card title="Risk summary">
          <div className="row">
            <Stat label="scored" value={summary.scored_identities} />
            <Stat label="average" value={summary.average_score} />
            <Stat label="critical" value={bands.critical ?? 0} tone={(bands.critical ?? 0) > 0 ? "bad" : undefined} />
            <Stat label="high" value={bands.high ?? 0} tone={(bands.high ?? 0) > 0 ? "warn" : undefined} />
            <Stat label="medium" value={bands.medium ?? 0} />
            <Stat label="low" value={bands.low ?? 0} tone={(bands.low ?? 0) > 0 ? "ok" : undefined} />
          </div>
          <p className="muted">
            Last run: {summary.run_at ? summary.run_at.slice(0, 19).replace("T", " ") : "never"}
            {summary.run_id ? ` · ${summary.run_id.slice(0, 8)}…` : ""}
          </p>
          {canRun && (
            <p>
              <button onClick={() => void computeNow()}>Compute now</button>
            </p>
          )}
        </Card>
      )}
      {summary && summary.top_risky.length > 0 && (
        <Card title="Top 10 riskiest identities">
          <table>
            <thead>
              <tr>
                <th>Identity</th>
                <th>Score</th>
                <th>Band</th>
                <th>Top factors</th>
              </tr>
            </thead>
            <tbody>
              {summary.top_risky.map((t) => (
                <tr key={t.employee_id}>
                  <td>
                    {t.name ?? t.employee_id} <span className="muted">({t.employee_id})</span>
                  </td>
                  <td>{t.score}</td>
                  <td>
                    <Badge tone={bandTone(t.band)}>{t.band}</Badge>
                  </td>
                  <td>
                    {t.top_factors.map((f) => (
                      <div key={f.signal}>
                        <Badge tone="neutral">{f.signal}</Badge> {f.contribution} — {f.detail}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      <Card title={`Snapshots${department ? ` — ${department}` : ""}`}>
        <div className="row">
          <select
            value={band}
            onChange={(e) => {
              setBand(e.target.value);
              setPage(1);
              void loadSnapshots(1, e.target.value, department);
            }}
          >
            <option value="">All bands</option>
            <option value="low">low</option>
            <option value="medium">medium</option>
            <option value="high">high</option>
            <option value="critical">critical</option>
          </select>
          <input
            placeholder="Filter by department"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void loadSnapshots(1, band, department);
            }}
          />
          <button
            className="secondary"
            onClick={() => void loadSnapshots(1, band, department)}
          >
            Apply
          </button>
        </div>
        {rows.length === 0 ? (
          <Empty>No snapshots. {canRun ? "Run a computation first." : "An admin must run a computation."}</Empty>
        ) : (
          <table>
            <thead>
              <tr>
                <th>Employee</th>
                <th>Name</th>
                <th>Department</th>
                <th>Score</th>
                <th>Band</th>
                <th>Trend</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.employee_id}</td>
                  <td>{r.name ?? "—"}</td>
                  <td>{r.department ?? "—"}</td>
                  <td>{r.score}</td>
                  <td>
                    <Badge tone={bandTone(r.band)}>{r.band}</Badge>
                  </td>
                  <td>
                    {r.identity_id != null && (
                      <button className="secondary" onClick={() => setTrendId(r.identity_id!)}>
                        View
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <p className="muted">
          Page {page}/{pages} · {total} rows
          {page > 1 && (
            <>
              {" "}
              <button className="secondary" onClick={() => void loadSnapshots(page - 1)}>
                ‹ Prev
              </button>
            </>
          )}
          {page < pages && (
            <>
              {" "}
              <button className="secondary" onClick={() => void loadSnapshots(page + 1)}>
                Next ›
              </button>
            </>
          )}
        </p>
      </Card>
      {trendId != null && <TrendPanel identityId={trendId} onClose={() => setTrendId(null)} />}
    </div>
  );
}
