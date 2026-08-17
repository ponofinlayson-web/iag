import type { ReactNode } from "react";

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="card">
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export function Badge({ tone, children }: { tone: "ok" | "warn" | "bad" | "neutral"; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

export function statusTone(status: string): "ok" | "warn" | "bad" | "neutral" {
  switch (status) {
    case "completed":
    case "approved":
    case "active":
      return "ok";
    case "pending":
    case "in_progress":
    case "staged":
    case "draft":
      return "warn";
    case "revoked":
    case "cancelled":
      return "bad";
    default:
      return "neutral";
  }
}

export function privilegeTone(level: string | null): "ok" | "warn" | "bad" | "neutral" {
  switch (level) {
    case "very_high":
      return "bad";
    case "high":
      return "warn";
    case "moderate":
      case "low":
      return "neutral";
  }
  return "neutral";
}

export function Spinner() {
  return <div className="spinner" aria-label="Loading" />;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="empty">{children}</p>;
}

export function errMsg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
