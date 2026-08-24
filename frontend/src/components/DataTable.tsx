import { useMemo, useRef, useState, type ReactNode } from "react";

/**
 * Generic client-side table: per-column filters, header sort, global
 * search with chips, column show/hide + drag reorder, sticky header and
 * pinned left columns. Column prefs persist to localStorage per view.
 */
import { useEffect } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render?: (row: T) => ReactNode;
  /** Sort/filter projection; defaults to String(row[key]). */
  value?: (row: T) => string | number;
  sortable?: boolean;
  /** "text" = substring input, "select" = dropdown of distinct values. */
  filter?: "text" | "select";
  /** Glued far-left, always visible, excluded from hide/reorder. */
  pinned?: boolean;
}

interface Prefs {
  hidden: string[];
  order: string[];
}

const PIN_W = [56, 220]; // id, name column widths for sticky offsets

function readPrefs(viewKey: string): Prefs {
  try {
    const raw = localStorage.getItem(`iag.cols.${viewKey}`);
    if (raw) {
      const p = JSON.parse(raw) as Prefs;
      if (Array.isArray(p.hidden) && Array.isArray(p.order)) return p;
    }
  } catch {
    /* corrupted prefs fall back to defaults */
  }
  return { hidden: [], order: [] };
}

export function DataTable<T>({
  viewKey,
  columns,
  rows,
  getRowKey,
  empty,
  searchable,
}: {
  viewKey: string;
  columns: Column<T>[];
  rows: T[];
  getRowKey: (row: T) => string | number;
  empty?: ReactNode;
  searchable?: boolean;
}) {
  const [prefs, setPrefs] = useState<Prefs>(() => readPrefs(viewKey));
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [chips, setChips] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [showCols, setShowCols] = useState(false);
  const dragFrom = useRef<number | null>(null);
  const colBtnRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    try {
      localStorage.setItem(`iag.cols.${viewKey}`, JSON.stringify(prefs));
    } catch {
      /* storage full/blocked: prefs are best-effort */
    }
  }, [viewKey, prefs]);

  useEffect(() => {
    function onDoc(e: MouseEvent) {
      if (colBtnRef.current && !colBtnRef.current.contains(e.target as Node)) setShowCols(false);
    }
    if (showCols) document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [showCols]);

  // Resolve column order: pinned first, then saved order, then definition
  // order; drop keys that no longer exist (schema evolved / stale prefs).
  const resolved = useMemo(() => {
    const ordered: Column<T>[] = [];
    for (const k of prefs.order) {
      const c = columns.find((x) => x.key === k && !x.pinned);
      if (c) ordered.push(c);
    }
    for (const c of columns) {
      if (!c.pinned && !ordered.includes(c)) ordered.push(c);
    }
    const pinnedCols = columns.filter((c) => c.pinned);
    const movable = ordered.filter(
      (c) => !prefs.hidden.includes(c.key),
    );
    return [...pinnedCols, ...movable];
  }, [columns, prefs]);

  const hiddenCount = useMemo(
    () => prefs.hidden.filter((k) => columns.some((c) => c.key === k)).length,
    [prefs.hidden, columns],
  );

  const val = (c: Column<T>, row: T): string => {
    if (c.value) {
      const v = c.value(row);
      return typeof v === "number" ? String(v) : v;
    }
    const v = (row as Record<string, unknown>)[c.key];
    return v == null ? "" : String(v);
  };

  const suggestions = useMemo(() => {
    if (!search.trim()) return [];
    const q = search.toLowerCase();
    const seen = new Set<string>();
    const out: string[] = [];
    for (const c of resolved) {
      for (const row of rows) {
        const v = val(c, row);
        if (v && v.toLowerCase().includes(q) && !seen.has(v)) {
          seen.add(v);
          out.push(v);
          if (out.length >= 8) return out;
        }
      }
    }
    return out;
  }, [search, resolved, rows]);

  const selectOptions = useMemo(() => {
    const m = new Map<string, Set<string>>();
    for (const c of resolved) {
      if (c.filter !== "select") continue;
      m.set(c.key, new Set(rows.map((r) => val(c, r)).filter(Boolean)));
    }
    return m;
  }, [resolved, rows]);

  const view = useMemo(() => {
    let out = rows;
    if (chips.length > 0) {
      out = out.filter((row) =>
        chips.every((chip) =>
          resolved.some((c) => val(c, row).toLowerCase().includes(chip.toLowerCase())),
        ),
      );
    }
    for (const [k, f] of Object.entries(filters)) {
      if (!f) continue;
      const c = resolved.find((x) => x.key === k);
      if (!c) continue;
      const needle = f.toLowerCase();
      out = out.filter((row) => val(c, row).toLowerCase().includes(needle));
    }
    if (sortKey) {
      const c = resolved.find((x) => x.key === sortKey);
      if (c) {
        const dir = sortDir === "asc" ? 1 : -1;
        const numeric = rows.every((r) => {
          const v = c.value ? c.value(r) : (r as Record<string, unknown>)[c.key];
          return v == null || v === "" || typeof v === "number" || !isNaN(Number(v));
        });
        out = [...out].sort((a, b) => {
          const va = val(c, a);
          const vb = val(c, b);
          if (numeric && va !== "" && vb !== "") {
            return (Number(va) - Number(vb)) * dir;
          }
          return va.localeCompare(vb) * dir;
        });
      }
    }
    return out;
  }, [rows, chips, filters, sortKey, sortDir, resolved]);

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  function drop(to: number) {
    const from = dragFrom.current;
    dragFrom.current = null;
    if (from == null || from === to) return;
    const movable = resolved.filter((c) => !c.pinned);
    const keys = movable.map((c) => c.key);
    const [moved] = keys.splice(from, 1);
    keys.splice(to, 0, moved);
    setPrefs((p) => ({ ...p, order: keys }));
  }

  const movable = resolved.filter((c) => !c.pinned);
  const pinLeft = (idx: number) =>
    idx <= 0 ? 0 : PIN_W.slice(0, idx).reduce((a, b) => a + b, 0);

  return (
    <div className="datatable">
      <div className="dt-toolbar">
        {searchable && (
          <div className="dt-search">
            {chips.map((chip) => (
              <span className="dt-chip" key={chip}>
                {chip}
                <button
                  className="dt-chip-x"
                  aria-label={`Remove filter ${chip}`}
                  onClick={() => setChips((cs) => cs.filter((c) => c !== chip))}
                >
                  ×
                </button>
              </span>
            ))}
            <input
              value={search}
              placeholder="Search table."
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && search.trim()) {
                  e.preventDefault();
                  setChips((cs) => (cs.includes(search.trim()) ? cs : [...cs, search.trim()]));
                  setSearch("");
                }
              }}
            />
            {search.trim() && suggestions.length > 0 && (
              <ul className="dt-suggest">
                {suggestions.map((s) => (
                  <li
                    key={s}
                    onMouseDown={(e) => {
                      e.preventDefault();
                      setChips((cs) => (cs.includes(s) ? cs : [...cs, s]));
                      setSearch("");
                    }}
                  >
                    {s}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
        <div className="spacer" />
        <div className="dt-cols" ref={colBtnRef}>
          <button className="secondary" onClick={() => setShowCols(!showCols)}>
            Columns{hiddenCount > 0 ? ` (${hiddenCount} hidden)` : ""}
          </button>
          {showCols && (
            <div className="dt-cols-popover">
              <p className="muted">Drag to reorder. Uncheck to hide.</p>
              {movable.map((c, i) => (
                <div
                  key={c.key}
                  className="dt-cols-row"
                  draggable
                  onDragStart={() => (dragFrom.current = i)}
                  onDragOver={(e) => e.preventDefault()}
                  onDrop={() => drop(i)}
                >
                  <span className="dt-cols-grip" aria-hidden>
                    ⠿
                  </span>
                  <label>
                    <input
                      type="checkbox"
                      checked={!prefs.hidden.includes(c.key)}
                      onChange={(e) =>
                        setPrefs((p) => ({
                          ...p,
                          hidden: e.target.checked
                            ? p.hidden.filter((k) => k !== c.key)
                            : [...p.hidden, c.key],
                        }))
                      }
                    />
                    {c.label}
                  </label>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
      <div className="dt-scroll">
        <table className="dt-table">
          <thead>
            <tr>
              {resolved.map((c, ci) => (
                <th
                  key={c.key}
                  className={c.pinned ? "dt-pinned" : undefined}
                  style={
                    c.pinned
                      ? { position: "sticky", left: pinLeft(ci), zIndex: 3 }
                      : undefined
                  }
                  aria-sort={sortKey === c.key ? (sortDir === "asc" ? "ascending" : "descending") : undefined}
                >
                  {c.sortable === false ? (
                    c.label
                    ) : (
                      <button
                        className={"dt-sort" + (sortKey === c.key ? " sorted" : "")}
                        onClick={() => toggleSort(c.key)}
                        title={`Sort by ${c.label}`}
                      >
                        {c.label}
                        {sortKey === c.key ? (sortDir === "asc" ? " ▲" : " ▼") : ""}
                      </button>
                    )}
                </th>
              ))}
            </tr>
            <tr className="dt-filter-row">
              {resolved.map((c, ci) => (
                <th
                  key={c.key}
                  className={c.pinned ? "dt-pinned" : undefined}
                  style={
                    c.pinned
                      ? { position: "sticky", left: pinLeft(ci), zIndex: 3, width: PIN_W[ci] }
                      : undefined
                  }
                >
                  {c.filter === "text" && (
                    <input
                      aria-label={`Filter ${c.label}`}
                      value={filters[c.key] ?? ""}
                      onChange={(e) => setFilters({ ...filters, [c.key]: e.target.value })}
                      placeholder="Filter"
                    />
                  )}
                  {c.filter === "select" && (
                    <select
                      aria-label={`Filter ${c.label}`}
                      value={filters[c.key] ?? ""}
                      onChange={(e) => setFilters({ ...filters, [c.key]: e.target.value })}
                    >
                      <option value="">All</option>
                      {[...(selectOptions.get(c.key) ?? [])]
                        .sort((a, b) => a.localeCompare(b))
                        .map((o) => (
                          <option key={o} value={o}>
                            {o}
                          </option>
                        ))}
                    </select>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {view.length === 0 && empty ? (
              <tr>
                <td colSpan={resolved.length}>{empty}</td>
              </tr>
            ) : (
              view.map((row) => (
                <tr key={getRowKey(row)}>
                  {resolved.map((c, ci) => {
                    const style: Record<string, string | number> | undefined =
                      c.pinned
                        ? {
                            position: "sticky",
                            left: pinLeft(ci),
                            zIndex: 2,
                            width: PIN_W[ci],
                            maxWidth: PIN_W[ci],
                          }
                        : undefined;
                    return (
                      <td key={c.key} className={c.pinned ? "dt-pinned" : undefined} style={style}>
                        {c.render ? c.render(row) : val(c, row)}
                      </td>
                    );
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <p className="muted dt-count">
        {view.length} of {rows.length} rows
      </p>
    </div>
  );
}
