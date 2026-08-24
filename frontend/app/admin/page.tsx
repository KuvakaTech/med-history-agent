"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { adminApi } from "@/lib/ticketing-api";
import type { AdminSession, TicketCategory } from "@/lib/ticketing-types";
import { getToken } from "@/lib/api";
import clsx from "clsx";

interface Stats {
  date_ist: string;
  today: { total: number; completed: number; partial: number; active: number; critical: number };
  all_time: { total: number; critical: number };
}

export default function AdminDashboard() {
  const router = useRouter();

  const [token, setToken]           = useState("");
  const [sessions, setSessions]     = useState<AdminSession[]>([]);
  const [categories, setCategories] = useState<TicketCategory[]>([]);
  const [stats, setStats]           = useState<Stats | null>(null);
  const [loading, setLoading]       = useState(true);
  const [fetching, setFetching]     = useState(false);
  const [error, setError]           = useState("");
  const [activeTab, setActiveTab]   = useState<"sessions" | "categories">("sessions");

  // Filters
  const [ticketSearch, setTicketSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [catFilter, setCatFilter]       = useState("");
  const [showDeleted, setShowDeleted]   = useState(false);
  const [dateFrom, setDateFrom]         = useState("");
  const [dateTo, setDateTo]             = useState("");

  // Category form
  const [newCatKey, setNewCatKey]     = useState("");
  const [newCatLabel, setNewCatLabel] = useState("");
  const [savingCat, setSavingCat]     = useState(false);

  // ── Initial load ──────────────────────────────────────────
  useEffect(() => {
    getToken()
      .then(async (t) => {
        setToken(t);
        const [s, c, st] = await Promise.all([
          adminApi.listSessions(t, { include_deleted: false }),
          adminApi.listCategories(t, true),
          adminApi.getStats(t).catch(() => null),
        ]);
        setSessions(s.sessions);
        setCategories(c.categories);
        if (st) setStats(st);
      })
      .catch((e) => {
        if (e.message?.includes("401") || e.message === "refresh_failed") {
          router.push("/login");
        } else {
          setError(e.message);
        }
      })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Fetch / search sessions ───────────────────────────────
  const refetch = useCallback(async () => {
    if (!token) return;
    setFetching(true);
    setError("");
    try {
      const s = await adminApi.listSessions(token, {
        status:          statusFilter || undefined,
        category:        catFilter || undefined,
        include_deleted: showDeleted,
        ticket:          ticketSearch || undefined,
        date_from:       dateFrom || undefined,
        date_to:         dateTo || undefined,
      });
      setSessions(s.sessions);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load sessions");
    } finally {
      setFetching(false);
    }
  }, [token, statusFilter, catFilter, showDeleted, ticketSearch, dateFrom, dateTo]);

  // Re-fetch when dropdowns/date change (not ticket — that needs explicit search)
  useEffect(() => {
    if (token) refetch();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, catFilter, showDeleted, dateFrom, dateTo, token]);

  // ── Category actions ──────────────────────────────────────
  const handleToggleCategory = async (catId: string, active: boolean) => {
    try {
      const updated = await adminApi.updateCategory(token, catId, { active: !active });
      setCategories((prev) =>
        prev.map((c) =>
          (c as unknown as { category_id: string }).category_id === catId ? updated : c
        )
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to update");
    }
  };

  const handleAddCategory = async () => {
    if (!newCatKey.trim() || !newCatLabel.trim()) return;
    setSavingCat(true);
    try {
      const cat = await adminApi.createCategory(token, {
        key:   newCatKey.trim().toLowerCase().replace(/\s+/g, "_"),
        label: newCatLabel.trim(),
      });
      setCategories((prev) => [...prev, cat]);
      setNewCatKey("");
      setNewCatLabel("");
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed");
    } finally {
      setSavingCat(false);
    }
  };

  if (loading) return <Spinner />;

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto" />
          <span className="text-sm font-semibold text-gray-700">Admin Dashboard</span>
        </div>
        {stats && (
          <span className="text-xs text-gray-400 hidden sm:block">
            {stats.date_ist}
          </span>
        )}
      </header>

      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {/* ── Stats cards ── */}
        {stats && (
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-3">
            <StatCard label="Today" value={stats.today.total} sub="check-ins" />
            <StatCard label="Completed" value={stats.today.completed} color="green" />
            <StatCard label="Partial" value={stats.today.partial} color="amber" />
            <StatCard label="Active" value={stats.today.active} color="blue" />
            <StatCard
              label="Critical today"
              value={stats.today.critical}
              color={stats.today.critical > 0 ? "red" : undefined}
              sub={`${stats.all_time.critical} all-time`}
            />
          </div>
        )}

        {/* ── Tabs ── */}
        <div className="flex gap-1 bg-gray-100 p-1 rounded-xl w-fit">
          {(["sessions", "categories"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                "px-5 py-2 rounded-lg text-sm font-semibold transition-all",
                activeTab === tab
                  ? "bg-white text-brand shadow-sm"
                  : "text-gray-500 hover:text-gray-700"
              )}
            >
              {tab === "sessions" ? `Sessions (${sessions.length})` : "Departments"}
            </button>
          ))}
        </div>

        {/* ── Sessions tab ── */}
        {activeTab === "sessions" && (
          <div className="space-y-4">
            {/* Filters row */}
            <div className="flex flex-wrap gap-3 items-end">
              {/* Ticket search */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Ticket No.
                </label>
                <div className="flex gap-2">
                  <input
                    className="input-field w-36 text-sm py-2 font-mono uppercase"
                    placeholder="TKT-000001"
                    value={ticketSearch}
                    onChange={(e) => setTicketSearch(e.target.value.toUpperCase())}
                    onKeyDown={(e) => e.key === "Enter" && refetch()}
                  />
                  <button
                    onClick={refetch}
                    disabled={fetching}
                    className="btn-secondary text-sm py-2 px-3"
                  >
                    {fetching ? "…" : "Search"}
                  </button>
                </div>
              </div>

              {/* Status */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Status
                </label>
                <select
                  className="input-field w-auto text-sm py-2"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="">All</option>
                  <option value="active">Active</option>
                  <option value="completed">Completed</option>
                  <option value="partial">Partial</option>
                </select>
              </div>

              {/* Department */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Department
                </label>
                <select
                  className="input-field w-auto text-sm py-2"
                  value={catFilter}
                  onChange={(e) => setCatFilter(e.target.value)}
                >
                  <option value="">All</option>
                  {categories.map((c) => (
                    <option key={c.key} value={c.key}>{c.label}</option>
                  ))}
                </select>
              </div>

              {/* Date range */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  From
                </label>
                <input
                  type="date"
                  className="input-field text-sm py-2"
                  value={dateFrom}
                  onChange={(e) => setDateFrom(e.target.value)}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  To
                </label>
                <input
                  type="date"
                  className="input-field text-sm py-2"
                  value={dateTo}
                  onChange={(e) => setDateTo(e.target.value)}
                />
              </div>

              {/* Include discarded */}
              <label className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer select-none pb-1">
                <input
                  type="checkbox"
                  checked={showDeleted}
                  onChange={(e) => setShowDeleted(e.target.checked)}
                  className="rounded"
                />
                Include discarded
              </label>
            </div>

            {sessions.length === 0 ? (
              <div className="card text-center py-12 text-gray-400 text-sm">
                No sessions found.
              </div>
            ) : (
              <div className="space-y-2">
                {sessions.map((s) => (
                  <SessionRow
                    key={s.session_id}
                    session={s}
                    onClick={() => router.push(`/admin/sessions/${s.session_id}`)}
                  />
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Categories tab ── */}
        {activeTab === "categories" && (
          <div className="space-y-4">
            <div className="card space-y-3">
              <h3 className="text-sm font-bold text-gray-700">Add Department</h3>
              <div className="flex gap-2">
                <input
                  className="input-field flex-1 text-sm py-2"
                  placeholder="Key (e.g. nephrology)"
                  value={newCatKey}
                  onChange={(e) => setNewCatKey(e.target.value)}
                />
                <input
                  className="input-field flex-1 text-sm py-2"
                  placeholder="Label (e.g. Nephrology)"
                  value={newCatLabel}
                  onChange={(e) => setNewCatLabel(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddCategory()}
                />
                <button
                  onClick={handleAddCategory}
                  disabled={savingCat || !newCatKey || !newCatLabel}
                  className="btn-primary py-2 px-4 text-sm"
                >
                  {savingCat ? "…" : "Add"}
                </button>
              </div>
            </div>

            <div className="space-y-2">
              {categories.map((cat) => {
                const c = cat as unknown as TicketCategory & {
                  category_id: string;
                  active: boolean;
                };
                return (
                  <div
                    key={c.category_id || c.key}
                    className="card flex items-center justify-between py-3"
                  >
                    <div>
                      <p className="text-sm font-semibold text-gray-800">{c.label}</p>
                      <p className="text-xs text-gray-400 font-mono">{c.key}</p>
                    </div>
                    <button
                      onClick={() => handleToggleCategory(c.category_id, c.active)}
                      className={clsx(
                        "text-xs font-semibold px-3 py-1.5 rounded-full transition-all",
                        c.active
                          ? "bg-green-100 text-green-700 hover:bg-red-50 hover:text-red-600"
                          : "bg-gray-100 text-gray-400 hover:bg-green-100 hover:text-green-700"
                      )}
                    >
                      {c.active ? "Active" : "Inactive"}
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

// ── Components ────────────────────────────────────────────────

function StatCard({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: number;
  sub?: string;
  color?: "green" | "amber" | "blue" | "red";
}) {
  const colorMap: Record<string, string> = {
    green: "text-green-700",
    amber: "text-amber-600",
    blue:  "text-blue-600",
    red:   "text-red-600",
  };
  return (
    <div className="card py-4 text-center space-y-1">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={clsx("text-3xl font-black", color ? colorMap[color] : "text-gray-900")}>
        {value}
      </p>
      {sub && <p className="text-xs text-gray-400">{sub}</p>}
    </div>
  );
}

function SessionRow({
  session,
  onClick,
}: {
  session: AdminSession;
  onClick: () => void;
}) {
  const statusColors: Record<string, string> = {
    completed: "bg-green-100 text-green-700",
    active:    "bg-blue-100 text-blue-700",
    partial:   "bg-amber-100 text-amber-700",
  };

  return (
    <div
      onClick={onClick}
      className={clsx(
        "card flex items-center justify-between py-3 cursor-pointer",
        "hover:border-brand/30 hover:shadow-sm transition-all",
        session.deleted_at && "opacity-60"
      )}
    >
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          {session.ticket_number && (
            <span className="text-sm font-black font-mono text-brand">
              {session.ticket_number}
            </span>
          )}
          <span
            className={clsx(
              "px-2 py-0.5 rounded-full text-xs font-semibold",
              statusColors[session.status] || "bg-gray-100 text-gray-600"
            )}
          >
            {session.status}
          </span>
          {session.category && (
            <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-brand-light text-brand">
              {session.category.label}
            </span>
          )}
          {session.deleted_at && (
            <span className="px-2 py-0.5 rounded-full text-xs bg-gray-100 text-gray-500">
              discarded
            </span>
          )}
          {session.flags?.some((f) => f.flag_type === "CRITICAL_RED_FLAG") && (
            <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-red-100 text-red-700">
              🚨 Critical
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 mt-1">
          <span className="text-xs text-gray-400">
            {session.started_at_ist || session.started_at}
          </span>
          <span className="text-xs text-gray-300 font-mono">
            {session.session_id.slice(0, 8)}
          </span>
          <span className="text-xs text-gray-400">{session.turn_count} turns</span>
        </div>
      </div>
      <span className="text-gray-300 ml-3">›</span>
    </div>
  );
}

function Spinner() {
  return (
    <div className="min-h-screen flex items-center justify-center">
      <svg className="animate-spin w-8 h-8 text-brand" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
      </svg>
    </div>
  );
}
