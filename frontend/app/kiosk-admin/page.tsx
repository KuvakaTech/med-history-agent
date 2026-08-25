"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { kioskAdminApi } from "@/lib/kiosk-admin-api";
import type { KioskAdminSession, KioskCentre } from "@/lib/kiosk-admin-types";
import { getToken } from "@/lib/api";
import clsx from "clsx";

interface Stats {
  date_ist: string;
  today: { total: number; completed: number; partial: number; active: number };
  all_time: { total: number; completed: number };
}

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
  const colors = {
    green: "text-green-700",
    amber: "text-amber-700",
    blue: "text-blue-700",
    red: "text-red-700",
  };
  return (
    <div className="card py-4 px-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={clsx("text-2xl font-bold mt-1", color ? colors[color] : "text-gray-900")}>
        {value}
      </p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

export default function KioskAdminDashboard() {
  const router = useRouter();
  const [token, setToken] = useState("");
  const [sessions, setSessions] = useState<KioskAdminSession[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const [fetching, setFetching] = useState(false);
  const [error, setError] = useState("");
  const [centreName, setCentreName] = useState("");

  const [centres, setCentres] = useState<KioskCentre[]>([]);
  const [selectedCentre, setSelectedCentre] = useState("");
  const [userRole, setUserRole] = useState("");

  const [complaintSearch, setComplaintSearch] = useState("");
  const [phoneSearch, setPhoneSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  const [showNewCentre, setShowNewCentre] = useState(false);
  const [newCentreSlug, setNewCentreSlug] = useState("");
  const [newCentreName, setNewCentreName] = useState("");
  const [creatingCentre, setCreatingCentre] = useState(false);

  const loadData = useCallback(
    async (t: string, centreId?: string, isSuperAdmin = false) => {
      setFetching(true);
      setError("");
      try {
        const cid = isSuperAdmin ? centreId : undefined;
        const [statsRes, sessionsRes, centreRes] = await Promise.all([
          kioskAdminApi.getStats(t, cid || undefined),
          kioskAdminApi.listSessions(t, {
            centre_id: cid || undefined,
            status: statusFilter || undefined,
            complaint: complaintSearch || undefined,
            phone: phoneSearch || undefined,
            date_from: dateFrom || undefined,
            date_to: dateTo || undefined,
            limit: 200,
          }),
          kioskAdminApi.getCurrentCentre(t, cid || null),
        ]);
        setStats(statsRes);
        setSessions(sessionsRes.sessions);
        setCentreName(centreRes.name);
      } catch (e: unknown) {
        setError(e instanceof Error ? e.message : "Failed to load data");
      } finally {
        setFetching(false);
      }
    },
    [statusFilter, complaintSearch, phoneSearch, dateFrom, dateTo]
  );

  useEffect(() => {
    getToken()
      .then(async (t) => {
        const payload = JSON.parse(atob(t.split(".")[1]));
        const role = payload.role;
        if (role !== "centre_admin" && role !== "super_admin") {
          router.push("/kiosk-admin/login");
          return;
        }
        setToken(t);
        setUserRole(role);
        if (role === "super_admin") {
          const { centres: list } = await kioskAdminApi.listCentres(t);
          setCentres(list);
          if (list.length > 0) {
            setSelectedCentre(list[0].centre_id);
            await loadData(t, list[0].centre_id, true);
          }
        } else {
          await loadData(t, undefined, false);
        }
      })
      .catch(() => router.push("/kiosk-admin/login"))
      .finally(() => setLoading(false));
  }, [router, loadData]);

  useEffect(() => {
    if (token && selectedCentre && userRole === "super_admin") {
      loadData(token, selectedCentre, true);
    }
  }, [selectedCentre, token, userRole, loadData]);

  const refetch = () => {
    if (!token) return;
    loadData(token, userRole === "super_admin" ? selectedCentre : undefined, userRole === "super_admin");
  };

  const handleCreateCentre = async () => {
    if (!token || !newCentreSlug.trim() || !newCentreName.trim()) return;
    setCreatingCentre(true);
    try {
      const c = await kioskAdminApi.createCentre(token, {
        slug: newCentreSlug.trim().toLowerCase(),
        name: newCentreName.trim(),
      });
      setCentres((prev) => [...prev, c]);
      setSelectedCentre(c.centre_id);
      setShowNewCentre(false);
      setNewCentreSlug("");
      setNewCentreName("");
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed");
    } finally {
      setCreatingCentre(false);
    }
  };

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500 text-sm">Loading…</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-amber-800">Kiosk Admin</span>
          <span className="text-sm text-gray-600">{centreName}</span>
          {userRole === "super_admin" && (
            <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs font-semibold rounded-full">
              Super Admin
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          {userRole === "super_admin" && centres.length > 0 && (
            <select
              className="input-field text-sm py-1 px-2"
              value={selectedCentre}
              onChange={(e) => setSelectedCentre(e.target.value)}
            >
              {centres.map((c) => (
                <option key={c.centre_id} value={c.centre_id}>{c.name}</option>
              ))}
            </select>
          )}
          {userRole === "super_admin" && (
            <button
              type="button"
              onClick={() => setShowNewCentre((v) => !v)}
              className="btn-secondary text-xs py-1.5 px-3"
            >
              + New Centre
            </button>
          )}
          {stats && (
            <span className="text-xs text-gray-400 hidden sm:block">{stats.date_ist}</span>
          )}
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {userRole === "super_admin" && showNewCentre && (
          <div className="card space-y-3">
            <h3 className="text-sm font-bold text-gray-700">Create Kiosk Centre</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <input
                className="input-field text-sm py-2"
                placeholder="Slug (e.g. varanasi-nagar-nigam)"
                value={newCentreSlug}
                onChange={(e) => setNewCentreSlug(e.target.value)}
              />
              <input
                className="input-field text-sm py-2"
                placeholder="Display name"
                value={newCentreName}
                onChange={(e) => setNewCentreName(e.target.value)}
              />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleCreateCentre}
                disabled={creatingCentre || !newCentreSlug.trim() || !newCentreName.trim()}
                className="btn-primary text-sm py-2 px-4"
              >
                {creatingCentre ? "…" : "Create"}
              </button>
              <button
                type="button"
                onClick={() => setShowNewCentre(false)}
                className="btn-secondary text-sm py-2 px-4"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {userRole === "super_admin" && !selectedCentre && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
            Select a kiosk centre to view grievances.
          </div>
        )}

        {(userRole !== "super_admin" || selectedCentre) && stats && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatCard label="Today" value={stats.today.total} sub="grievances" />
            <StatCard label="Completed" value={stats.today.completed} color="green" />
            <StatCard label="Partial" value={stats.today.partial} color="amber" />
            <StatCard label="Active" value={stats.today.active} color="blue" />
          </div>
        )}

        {(userRole !== "super_admin" || selectedCentre) && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-3 items-end">
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase">Complaint No.</label>
                <input
                  className="input-field w-44 text-sm py-2 font-mono"
                  placeholder="JS-VNS-…"
                  value={complaintSearch}
                  onChange={(e) => setComplaintSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && refetch()}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase">Phone</label>
                <input
                  className="input-field w-36 text-sm py-2 font-mono"
                  placeholder="9876543210"
                  value={phoneSearch}
                  onChange={(e) => setPhoneSearch(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && refetch()}
                />
              </div>
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase">Status</label>
                <select
                  className="input-field text-sm py-2"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                >
                  <option value="">All</option>
                  <option value="completed">Completed</option>
                  <option value="partial">Partial</option>
                  <option value="active">Active</option>
                </select>
              </div>
              <button type="button" onClick={refetch} disabled={fetching} className="btn-secondary text-sm py-2 px-4">
                {fetching ? "…" : "Search"}
              </button>
            </div>

            <div className="card overflow-hidden">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 border-b border-gray-100">
                  <tr>
                    <th className="text-left px-4 py-3 font-semibold text-gray-500">Complaint</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-500">Phone</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-500">Summary</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-500">Status</th>
                    <th className="text-left px-4 py-3 font-semibold text-gray-500">Started</th>
                  </tr>
                </thead>
                <tbody>
                  {sessions.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-gray-400">
                        No grievances found.
                      </td>
                    </tr>
                  ) : (
                    sessions.map((s) => (
                      <tr
                        key={s.session_id}
                        className="border-b border-gray-50 hover:bg-amber-50/50 cursor-pointer"
                        onClick={() => router.push(`/kiosk-admin/sessions/${s.session_id}`)}
                      >
                        <td className="px-4 py-3 font-mono text-amber-800">
                          {s.complaint_number || "—"}
                        </td>
                        <td className="px-4 py-3 font-mono text-gray-600">{s.phone}</td>
                        <td className="px-4 py-3 text-gray-700 max-w-xs truncate">
                          {s.grievance_summary || "—"}
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={clsx(
                              "text-xs font-semibold px-2 py-0.5 rounded-full",
                              s.status === "completed" && "bg-green-100 text-green-700",
                              s.status === "partial" && "bg-amber-100 text-amber-700",
                              s.status === "active" && "bg-blue-100 text-blue-700"
                            )}
                          >
                            {s.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-gray-500 text-xs">
                          {s.started_at_ist || "—"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
