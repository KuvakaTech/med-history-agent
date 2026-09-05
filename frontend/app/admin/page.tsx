"use client";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { adminApi } from "@/lib/ticketing-api";
import type { AdminSession, Hospital, TicketCategory } from "@/lib/ticketing-types";
import { visitTypeBadge } from "@/lib/ticketing-types";
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

  // Hospital selection for super admins
  const [hospitals, setHospitals]   = useState<Hospital[]>([]);
  const [selectedHospital, setSelectedHospital] = useState("");
  const [userRole, setUserRole]     = useState("");

  // Filters
  const [ticketSearch, setTicketSearch] = useState("");
  const [phoneSearch, setPhoneSearch]   = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [catFilter, setCatFilter]       = useState("");
  const [showDeleted, setShowDeleted]   = useState(false);
  const [dateFrom, setDateFrom]         = useState("");
  const [dateTo, setDateTo]             = useState("");

  // Category form
  const [newCatKey, setNewCatKey]     = useState("");
  const [newCatLabel, setNewCatLabel] = useState("");
  const [savingCat, setSavingCat]     = useState(false);
  const [editingCatId, setEditingCatId] = useState<string | null>(null);
  const [editLabel, setEditLabel]       = useState("");

  // New hospital form (super admin only)
  const [showNewHospital, setShowNewHospital] = useState(false);
  const [newHospitalSlug, setNewHospitalSlug] = useState("");
  const [newHospitalName, setNewHospitalName] = useState("");
  const [newHospitalLang, setNewHospitalLang] = useState("hi");
  const [newHospitalPin, setNewHospitalPin] = useState("");
  const [creatingHospital, setCreatingHospital] = useState(false);

  const [kioskPin, setKioskPin] = useState("");
  const [savingPin, setSavingPin] = useState(false);
  const [collectCaste, setCollectCaste] = useState(false);
  const [savingCaste, setSavingCaste] = useState(false);

  const [showNewStaff, setShowNewStaff] = useState(false);
  const [staffEmail, setStaffEmail] = useState("");
  const [staffName, setStaffName] = useState("");
  const [staffPassword, setStaffPassword] = useState("");
  const [staffRole, setStaffRole] = useState<"doctor" | "hospital_admin">("doctor");
  const [staffHospitalId, setStaffHospitalId] = useState("");
  const [creatingStaff, setCreatingStaff] = useState(false);

  // ── Initial load ──────────────────────────────────────────
  useEffect(() => {
    getToken()
      .then(async (t) => {
        setToken(t);
        
        // Decode token to get user role
        const payload = JSON.parse(atob(t.split('.')[1]));
        const role = payload.role;
        setUserRole(role);
        
        // Load hospitals if super admin
        if (role === "super_admin") {
          try {
            const hospitalsResponse = await adminApi.listHospitals(t);
            setHospitals(hospitalsResponse.hospitals);
            
            // Auto-select first hospital if available
            if (hospitalsResponse.hospitals.length > 0) {
              const firstHospitalId = hospitalsResponse.hospitals[0].hospital_id;
              setSelectedHospital(firstHospitalId);
              
              // Load data with first hospital
              await loadDataForHospital(t, firstHospitalId, role);
            }
          } catch (e) {
            console.error("Failed to load hospitals:", e);
            setError("Failed to load hospitals. Please check console for details.");
          }
        } else {
          // Hospital admin - load data without hospital_id
          await loadDataForHospital(t, null, role);
        }
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

  // Helper function to load data for a specific hospital
  const loadDataForHospital = async (t: string, hospital_id: string | null, role?: string) => {
    try {
      const roleNow = role || userRole;
      const [s, st] = await Promise.all([
        adminApi.listSessions(t, { include_deleted: false }, hospital_id),
        adminApi.getStats(t, hospital_id || undefined).catch(() => null),
      ]);
      setSessions(s.sessions);
      if (st) setStats(st);
      if (roleNow !== "doctor") {
        const c = await adminApi.listCategories(t, true, hospital_id);
        setCategories(c.categories);
        const hospital = await adminApi.getCurrentHospital(t, hospital_id).catch(() => null);
        setCollectCaste(!!hospital?.collect_caste);
      } else {
        setCategories([]);
      }
    } catch (e) {
      throw e;
    }
  };

  // Handle hospital selection change
  useEffect(() => {
    if (token && selectedHospital && userRole === "super_admin") {
      setLoading(true);
      loadDataForHospital(token, selectedHospital)
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedHospital, token, userRole]);

  // ── Fetch / search sessions ───────────────────────────────
  const refetch = useCallback(async () => {
    if (!token) return;
    setFetching(true);
    setError("");
    try {
      const hospital_id = userRole === "super_admin" ? selectedHospital : null;
      const s = await adminApi.listSessions(token, {
        status:          statusFilter || undefined,
        category:        catFilter || undefined,
        include_deleted: showDeleted,
        ticket:          ticketSearch || undefined,
        phone:           phoneSearch || undefined,
        date_from:       dateFrom || undefined,
        date_to:         dateTo || undefined,
      }, hospital_id);
      setSessions(s.sessions);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load sessions");
    } finally {
      setFetching(false);
    }
  }, [token, statusFilter, catFilter, showDeleted, ticketSearch, phoneSearch, dateFrom, dateTo, userRole, selectedHospital]);

  // Re-fetch when dropdowns/date change (not ticket — that needs explicit search)
  useEffect(() => {
    if (token) refetch();
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, catFilter, showDeleted, dateFrom, dateTo, token, userRole, selectedHospital]);

  // ── Category actions ──────────────────────────────────────
  const handleToggleCategory = async (catId: string, active: boolean) => {
    try {
      const hospital_id = userRole === "super_admin" ? selectedHospital : null;
      const updated = await adminApi.updateCategory(token, catId, { active: !active }, hospital_id);
      setCategories((prev) =>
        prev.map((c) =>
          (c as unknown as { category_id: string }).category_id === catId ? updated : c
        )
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to update");
    }
  };

  const handleRenameCategory = async (catId: string) => {
    const label = editLabel.trim();
    if (!label) return;
    try {
      const hospital_id = userRole === "super_admin" ? selectedHospital : null;
      const updated = await adminApi.updateCategory(token, catId, { label }, hospital_id);
      setCategories((prev) =>
        prev.map((c) =>
          (c as unknown as { category_id: string }).category_id === catId ? updated : c
        )
      );
      setEditingCatId(null);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to rename");
    }
  };

  const handleCreateHospital = async () => {
    const slug = newHospitalSlug.trim().toLowerCase().replace(/\s+/g, "-");
    const name = newHospitalName.trim();
    if (!slug || !name) return;
    setCreatingHospital(true);
    try {
      const hospital = await adminApi.createHospital(token, {
        slug,
        name,
        default_language: newHospitalLang,
        ...(newHospitalPin.trim() ? { kiosk_pin: newHospitalPin.trim() } : {}),
      });
      setHospitals((prev) => [...prev, hospital]);
      setSelectedHospital(hospital.hospital_id);
      setNewHospitalSlug("");
      setNewHospitalName("");
      setNewHospitalLang("hi");
      setNewHospitalPin("");
      setShowNewHospital(false);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to create hospital");
    } finally {
      setCreatingHospital(false);
    }
  };

  const handleSetKioskPin = async () => {
    const pin = kioskPin.trim();
    if (!/^\d{4,8}$/.test(pin)) {
      alert("PIN must be 4–8 digits.");
      return;
    }
    setSavingPin(true);
    try {
      const hospital_id = userRole === "super_admin" ? selectedHospital : null;
      await adminApi.setKioskPin(token, pin, hospital_id);
      setKioskPin("");
      setHospitals((prev) =>
        prev.map((h) =>
          h.hospital_id === (hospital_id || h.hospital_id)
            ? { ...h, has_kiosk_pin: true }
            : h
        )
      );
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to set PIN");
    } finally {
      setSavingPin(false);
    }
  };

  const handleToggleCaste = async () => {
    setSavingCaste(true);
    try {
      const hospital_id = userRole === "super_admin" ? selectedHospital : null;
      const updated = await adminApi.setHospitalSettings(
        token,
        { collect_caste: !collectCaste },
        hospital_id
      );
      setCollectCaste(!!updated.collect_caste);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to update setting");
    } finally {
      setSavingCaste(false);
    }
  };

  const handleCreateStaff = async () => {
    if (!staffEmail.trim() || !staffName.trim() || staffPassword.length < 8 || !staffHospitalId) {
      return;
    }
    setCreatingStaff(true);
    try {
      await adminApi.createAdminUser(token, {
        email: staffEmail.trim(),
        name: staffName.trim(),
        password: staffPassword,
        role: staffRole,
        hospital_id: staffHospitalId,
      });
      setStaffEmail("");
      setStaffName("");
      setStaffPassword("");
      setStaffRole("doctor");
      setShowNewStaff(false);
    } catch (e: unknown) {
      alert(e instanceof Error ? e.message : "Failed to create staff");
    } finally {
      setCreatingStaff(false);
    }
  };

  const handleAddCategory = async () => {
    if (!newCatKey.trim() || !newCatLabel.trim()) return;
    setSavingCat(true);
    try {
      const hospital_id = userRole === "super_admin" ? selectedHospital : null;
      const cat = await adminApi.createCategory(token, {
        key:   newCatKey.trim().toLowerCase().replace(/\s+/g, "_"),
        label: newCatLabel.trim(),
      }, hospital_id);
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
          <span className="text-sm font-semibold text-gray-700">
            {userRole === "doctor" ? "Doctor Dashboard" : "Admin Dashboard"}
          </span>
          {userRole === "super_admin" && (
            <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs font-semibold rounded-full">
              Super Admin
            </span>
          )}
          {userRole === "doctor" && (
            <span className="px-2 py-1 bg-blue-100 text-blue-700 text-xs font-semibold rounded-full">
              Doctor
            </span>
          )}
        </div>
        <div className="flex items-center gap-4">
          {userRole === "super_admin" && (
            <div className="flex items-center gap-2">
              {hospitals.length > 0 && (
                <>
                  <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                    Hospital:
                  </label>
                  <select
                    className="input-field text-sm py-1 px-2 min-w-0"
                    value={selectedHospital}
                    onChange={(e) => setSelectedHospital(e.target.value)}
                  >
                    <option value="">Select Hospital</option>
                    {hospitals.map((h) => (
                      <option key={h.hospital_id} value={h.hospital_id}>
                        {h.name}
                      </option>
                    ))}
                  </select>
                </>
              )}
              <button
                onClick={() => setShowNewHospital((v) => !v)}
                className="btn-secondary text-xs py-1.5 px-3"
              >
                + New Hospital
              </button>
              <button
                onClick={() => setShowNewStaff((v) => !v)}
                className="btn-secondary text-xs py-1.5 px-3"
              >
                + Staff
              </button>
            </div>
          )}
          {stats && (
            <span className="text-xs text-gray-400 hidden sm:block">
              {stats.date_ist}
            </span>
          )}
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-4 py-8 space-y-6">
        {error && (
          <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {userRole === "super_admin" && showNewHospital && (
          <div className="card space-y-3">
            <h3 className="text-sm font-bold text-gray-700">Create Hospital</h3>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <input
                className="input-field text-sm py-2"
                placeholder="Slug (e.g. aiims-delhi)"
                value={newHospitalSlug}
                onChange={(e) => setNewHospitalSlug(e.target.value)}
              />
              <input
                className="input-field text-sm py-2"
                placeholder="Name (e.g. AIIMS Delhi)"
                value={newHospitalName}
                onChange={(e) => setNewHospitalName(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleCreateHospital()}
              />
              <select
                className="input-field text-sm py-2"
                value={newHospitalLang}
                onChange={(e) => setNewHospitalLang(e.target.value)}
              >
                <option value="hi">Hindi (default)</option>
                <option value="en">English</option>
              </select>
              <input
                className="input-field text-sm py-2"
                placeholder="Kiosk PIN (4–8 digits, optional)"
                inputMode="numeric"
                value={newHospitalPin}
                onChange={(e) => setNewHospitalPin(e.target.value.replace(/\D/g, "").slice(0, 8))}
              />
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCreateHospital}
                disabled={creatingHospital || !newHospitalSlug.trim() || !newHospitalName.trim()}
                className="btn-primary text-sm py-2 px-4"
              >
                {creatingHospital ? "…" : "Create"}
              </button>
              <button
                onClick={() => setShowNewHospital(false)}
                className="btn-secondary text-sm py-2 px-4"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {userRole === "super_admin" && showNewStaff && (
          <div className="card space-y-3">
            <h3 className="text-sm font-bold text-gray-700">Create Staff</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <input
                className="input-field text-sm py-2"
                placeholder="Email"
                value={staffEmail}
                onChange={(e) => setStaffEmail(e.target.value)}
              />
              <input
                className="input-field text-sm py-2"
                placeholder="Name"
                value={staffName}
                onChange={(e) => setStaffName(e.target.value)}
              />
              <input
                className="input-field text-sm py-2"
                type="password"
                placeholder="Password (8+ characters)"
                value={staffPassword}
                onChange={(e) => setStaffPassword(e.target.value)}
              />
              <select
                className="input-field text-sm py-2"
                value={staffRole}
                onChange={(e) => setStaffRole(e.target.value as "doctor" | "hospital_admin")}
              >
                <option value="doctor">Doctor (view patients)</option>
                <option value="hospital_admin">Hospital admin</option>
              </select>
              <select
                className="input-field text-sm py-2 sm:col-span-2"
                value={staffHospitalId}
                onChange={(e) => setStaffHospitalId(e.target.value)}
              >
                <option value="">Select hospital</option>
                {hospitals.map((h) => (
                  <option key={h.hospital_id} value={h.hospital_id}>
                    {h.name}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex gap-2">
              <button
                onClick={handleCreateStaff}
                disabled={
                  creatingStaff ||
                  !staffEmail.trim() ||
                  !staffName.trim() ||
                  staffPassword.length < 8 ||
                  !staffHospitalId
                }
                className="btn-primary text-sm py-2 px-4"
              >
                {creatingStaff ? "…" : "Create"}
              </button>
              <button
                onClick={() => setShowNewStaff(false)}
                className="btn-secondary text-sm py-2 px-4"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {userRole === "super_admin" && !selectedHospital && !showNewHospital && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-700">
            {hospitals.length === 0
              ? "No hospitals yet — click \"+ New Hospital\" above to create one."
              : "Please select a hospital to view data."}
          </div>
        )}

        {(userRole !== "super_admin" || selectedHospital) && userRole !== "doctor" && (
          <div className="card space-y-3">
            <h3 className="text-sm font-bold text-gray-700">Kiosk PIN</h3>
            <p className="text-xs text-gray-500">
              Staff enter this PIN on the check-in screen. 4–8 digits.
            </p>
            <div className="flex gap-2">
              <input
                className="input-field text-sm py-2 w-40"
                placeholder="••••"
                inputMode="numeric"
                value={kioskPin}
                onChange={(e) => setKioskPin(e.target.value.replace(/\D/g, "").slice(0, 8))}
                onKeyDown={(e) => e.key === "Enter" && handleSetKioskPin()}
              />
              <button
                onClick={handleSetKioskPin}
                disabled={savingPin || kioskPin.length < 4}
                className="btn-primary text-sm py-2 px-4"
              >
                {savingPin ? "…" : "Set PIN"}
              </button>
            </div>
            <div className="flex items-center justify-between pt-2 border-t border-gray-100">
              <div>
                <p className="text-sm font-medium text-gray-700">Ask caste at check-in</p>
                <p className="text-xs text-gray-500">Shows General, OBC, SC, ST after gender.</p>
              </div>
              <button
                type="button"
                disabled={savingCaste}
                onClick={handleToggleCaste}
                className={clsx(
                  "relative inline-flex h-7 w-12 shrink-0 rounded-full transition-colors",
                  collectCaste ? "bg-brand" : "bg-gray-200"
                )}
                aria-pressed={collectCaste}
              >
                <span
                  className={clsx(
                    "pointer-events-none inline-block h-6 w-6 mt-0.5 rounded-full bg-white shadow transition-transform",
                    collectCaste ? "translate-x-5" : "translate-x-0.5"
                  )}
                />
              </button>
            </div>
          </div>
        )}

        {/* Show content only if hospital is selected (for super admin) or if user is hospital admin */}
        {(userRole !== "super_admin" || selectedHospital) && (
          <>
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
              {(userRole === "doctor" ? (["sessions"] as const) : (["sessions", "categories"] as const)).map((tab) => (
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
          </>
        )}

        {/* ── Sessions tab ── */}
        {(userRole !== "super_admin" || selectedHospital) && activeTab === "sessions" && (
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

              {/* Phone search */}
              <div className="space-y-1">
                <label className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
                  Mobile No.
                </label>
                <div className="flex gap-2">
                  <input
                    className="input-field w-36 text-sm py-2 font-mono"
                    placeholder="9876543210"
                    value={phoneSearch}
                    onChange={(e) => setPhoneSearch(e.target.value)}
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
        {(userRole !== "super_admin" || selectedHospital) && userRole !== "doctor" && activeTab === "categories" && (
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
                const isEditing = editingCatId === c.category_id;
                return (
                  <div
                    key={c.category_id || c.key}
                    className="card flex items-center justify-between py-3 gap-3"
                  >
                    {isEditing ? (
                      <div className="flex-1 flex items-center gap-2">
                        <input
                          autoFocus
                          className="input-field flex-1 text-sm py-1.5"
                          value={editLabel}
                          onChange={(e) => setEditLabel(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") handleRenameCategory(c.category_id);
                            if (e.key === "Escape") setEditingCatId(null);
                          }}
                        />
                        <button
                          onClick={() => handleRenameCategory(c.category_id)}
                          className="btn-primary text-xs py-1.5 px-3"
                        >
                          Save
                        </button>
                        <button
                          onClick={() => setEditingCatId(null)}
                          className="btn-secondary text-xs py-1.5 px-3"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <div>
                        <p className="text-sm font-semibold text-gray-800">{c.label}</p>
                        <p className="text-xs text-gray-400 font-mono">{c.key}</p>
                      </div>
                    )}
                    {!isEditing && (
                      <div className="flex items-center gap-2 flex-shrink-0">
                        <button
                          onClick={() => {
                            setEditingCatId(c.category_id);
                            setEditLabel(c.label);
                          }}
                          className="text-xs font-semibold px-3 py-1.5 rounded-full bg-gray-100 text-gray-500 hover:bg-brand-light hover:text-brand transition-all"
                        >
                          Edit
                        </button>
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
                    )}
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
          {session.opd_number != null && (
            <span className="text-base font-black font-mono text-brand">
              OPD {session.opd_number}
            </span>
          )}
          {session.ticket_number && (
            <span className="text-xs font-mono text-gray-400">
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
          {session.visit_type && (
            <span className="px-2 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-100">
              {visitTypeBadge(session.visit_type)}
            </span>
          )}
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
