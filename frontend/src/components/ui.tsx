import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type ReactNode } from "react";

const FOCUSABLE =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Shared dialog: overlay + Esc/backdrop close + focus trap + restore.
 * Conditionally rendered by the caller (renders null when closed is the
 * caller's `open && <Modal>`). Children own form state so parent
 * re-renders don't fight the focus management here.
 */
export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    const node = ref.current;
    if (node) {
      const first = node.querySelector<HTMLElement>(FOCUSABLE);
      (first ?? node).focus();
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        closeRef.current();
        return;
      }
      if (e.key !== "Tab" || !ref.current) return;
      const items = Array.from(ref.current.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
        (el) => !el.hasAttribute("disabled") && el.offsetParent !== null,
      );
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      prev?.focus();
    };
  }, []);

  return (
    <div
      className="modal-overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) closeRef.current();
      }}
    >
      <div
        className={"modal" + (wide ? " modal-wide" : "")}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
        tabIndex={-1}
      >
        <h3>{title}</h3>
        {children}
      </div>
    </div>
  );
}

export interface TypeaheadItem {
  id: number;
  label: string;
  /** Optional submit value (e.g. employee_id) distinct from the label. */
  value?: string;
  sub?: string;
}

/**
 * Debounced autocomplete over a caller-supplied lookup (e.g. identity
 * search). Selection is authoritative: editing text clears it and the
 * parent gets onSelect(null) — validation lives there.
 */
export function Typeahead({
  lookup,
  onSelect,
  onTextChange,
  placeholder,
}: {
  lookup: (q: string) => Promise<TypeaheadItem[]>;
  onSelect: (item: TypeaheadItem | null) => void;
  onTextChange?: (text: string) => void;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [items, setItems] = useState<TypeaheadItem[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(-1);
  const timer = useRef<number | undefined>(undefined);
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  function change(v: string) {
    setText(v);
    onTextChange?.(v);
    onSelect(null);
    window.clearTimeout(timer.current);
    if (!v.trim()) {
      setItems([]);
      setOpen(false);
      return;
    }
    timer.current = window.setTimeout(() => {
      lookup(v.trim())
        .then((res) => {
          setItems(res);
          setActive(res.length > 0 ? 0 : -1);
          setOpen(true);
        })
        .catch(() => setItems([]));
    }, 250);
  }

  function pick(it: TypeaheadItem) {
    setText(it.label);
    onSelect(it);
    setOpen(false);
  }

  function key(e: ReactKeyboardEvent<HTMLInputElement>) {
    if (!open || items.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % items.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + items.length) % items.length);
    } else if (e.key === "Enter" && active >= 0) {
      e.preventDefault();
      pick(items[active]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  }

  return (
    <div className="typeahead" ref={rootRef}>
      <input
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
        autoComplete="off"
        value={text}
        placeholder={placeholder}
        onChange={(e) => change(e.target.value)}
        onKeyDown={key}
        onFocus={() => {
          if (items.length > 0) setOpen(true);
        }}
      />
      {open && (
        <ul className="typeahead-list" role="listbox">
          {items.length === 0 && <li className="typeahead-empty">No matches</li>}
          {items.map((it, i) => (
            <li
              key={it.id}
              role="option"
              aria-selected={i === active}
              className={"typeahead-item" + (i === active ? " active" : "")}
              onMouseEnter={() => setActive(i)}
              onMouseDown={(e) => {
                e.preventDefault();
                pick(it);
              }}
            >
              {it.label}
              {it.sub && <span className="typeahead-sub">{it.sub}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="card">
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

export function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: "ok" | "warn" | "bad" }) {
  return (
    <div className="stat">
      <div className={"stat-value" + (tone ? ` stat-value-${tone}` : "")}>{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

export type BadgeTone = "ok" | "warn" | "bad" | "neutral" | "info" | "accent";

export function Badge({ tone, children }: { tone: BadgeTone; children: ReactNode }) {
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
