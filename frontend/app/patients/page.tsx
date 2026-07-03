"use client";
import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { UserPlus, Search, LogOut, ChevronRight, User, X } from "lucide-react";
import { api, getToken } from "@/lib/api";
import { getUser, type User as AuthUser } from "@/lib/auth";
import type { Patient } from "@/lib/types";

const AVATAR_PALETTES = [
  "bg-brand-light text-brand",
  "bg-blue-100 text-blue-700",
  "bg-emerald-100 text-emerald-700",
  "bg-amber-100 text-amber-800",
  "bg-rose-100 text-rose-700",
];

const GENDER_BADGE: Record<string, string> = {
  Male:   "bg-blue-50 text-blue-600 border border-blue-100",
  Female: "bg-pink-50 text-pink-600 border border-pink-100",
  Other:  "bg-purple-50 text-purple-600 border border-purple-100",
};

function avatarPalette(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xfffff;
  return AVATAR_PALETTES[h % AVATAR_PALETTES.length];
}

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

export default function PatientsPage() {
  const router = useRouter();
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [patients, setPatients] = useState<Patient[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createAge, setCreateAge] = useState("");
  const [createGender, setCreateGender] = useState("");
  const [createPhone, setCreatePhone] = useState("");
  const [creating, setCreating] = useState(false);
  const [createError, setCreateError] = useState("");

  const loadPatients = useCallback(async () => {
    const data = await api.listPatients();
    setPatients(data.patients);
  }, []);

  useEffect(() => {
    getToken()
      .then(() => { setAuthUser(getUser()); return loadPatients(); })
      .catch(() => router.replace("/login"))
      .finally(() => setLoading(false));
  }, [router, loadPatients]);

  const handleLogout = async () => {
    await api.logout();
    router.replace("/login");
  };

  const closeModal = () => {
    setShowCreate(false);
    setCreateError("");
    setCreateName(""); setCreateAge(""); setCreateGender(""); setCreatePhone("");
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) { setCreateError("Name is required."); return; }
    if (!createAge || isNaN(Number(createAge)) || Number(createAge) < 1) {
      setCreateError("Valid age is required."); return;
    }
    setCreateError("");
    setCreating(true);
    try {
      const patient = await api.createPatient(
        createName.trim(), Number(createAge),
        createGender || undefined, createPhone.trim() || undefined,
      );
      setPatients((p) => [patient, ...p]);
      closeModal();
      router.push(`/patients/${patient.patient_id}`);
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "Failed to create patient.");
    } finally {
      setCreating(false);
    }
  };

  const filtered = patients.filter((p) =>
    p.name.toLowerCase().includes(search.toLowerCase())
  );

  if (loading) return null;

  return (
    <main className="min-h-screen bg-gray-50">
      {/* ── Header ── */}
      <header className="sticky top-0 z-30 bg-white border-b border-gray-100 px-6 py-0">
        <div className="max-w-5xl mx-auto flex items-center justify-between h-14">
          {/* Logo */}
          <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-7 w-auto" />

          {/* Right */}
          <div className="flex items-center gap-4">
            {authUser && (
              <span className="hidden sm:block text-sm text-gray-500 font-medium">{authUser.name}</span>
            )}
            <button
              onClick={handleLogout}
              className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              <span className="hidden sm:inline">Sign out</span>
            </button>
          </div>
        </div>
      </header>

      {/* ── Content ── */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        {/* Title row */}
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 leading-tight">
              Patients
              {patients.length > 0 && (
                <span className="ml-2.5 text-base font-semibold text-gray-400">{patients.length}</span>
              )}
            </h1>
            <p className="text-gray-500 text-sm mt-0.5">Manage and view your patient records</p>
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="btn-primary flex items-center gap-2 px-4 py-2.5 text-sm"
          >
            <UserPlus className="w-4 h-4" />
            New Patient
          </button>
        </div>

        {/* Search */}
        {patients.length > 0 && (
          <div className="relative mb-6 max-w-sm">
            <Search className="absolute left-3.5 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <input
              type="text"
              placeholder="Search patients…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-white border border-gray-200 rounded-xl pl-10 pr-4 py-2.5 text-sm text-gray-900 placeholder-gray-400
                         focus:outline-none focus:border-brand focus:ring-4 focus:ring-brand/10 transition-all"
            />
          </div>
        )}

        {/* Empty state */}
        {filtered.length === 0 ? (
          <div className="text-center py-24">
            <div className="w-14 h-14 rounded-2xl bg-brand-light flex items-center justify-center mx-auto mb-4">
              <User className="w-7 h-7 text-brand" />
            </div>
            <p className="text-gray-800 font-semibold text-base mb-1">
              {search ? "No patients found" : "No patients yet"}
            </p>
            <p className="text-gray-400 text-sm">
              {search ? `No results for "${search}"` : "Create your first patient to get started."}
            </p>
            {!search && (
              <button
                onClick={() => setShowCreate(true)}
                className="btn-primary inline-flex items-center gap-2 px-5 py-2.5 text-sm mt-5"
              >
                <UserPlus className="w-4 h-4" />
                Add first patient
              </button>
            )}
          </div>
        ) : (
          /* Patient grid */
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((p) => (
              <button
                key={p.patient_id}
                onClick={() => router.push(`/patients/${p.patient_id}`)}
                className="group text-left bg-white border border-gray-100 hover:border-brand/30 rounded-2xl p-5 transition-all duration-150 hover:shadow-md hover:shadow-brand/5"
              >
                <div className="flex items-start gap-3 mb-4">
                  <div className={`w-10 h-10 rounded-xl flex items-center justify-center text-sm font-bold flex-shrink-0 ${avatarPalette(p.name)}`}>
                    {initials(p.name)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-gray-900 font-semibold text-sm truncate group-hover:text-brand transition-colors">
                      {p.name}
                    </p>
                    <p className="text-gray-400 text-xs mt-0.5">
                      {p.age} yrs{p.gender ? ` · ${p.gender}` : ""}
                    </p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-gray-300 group-hover:text-brand transition-colors mt-0.5 flex-shrink-0" />
                </div>

                <div className="flex items-center justify-between">
                  {p.gender ? (
                    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${GENDER_BADGE[p.gender] ?? "bg-gray-100 text-gray-600 border border-gray-200"}`}>
                      {p.gender}
                    </span>
                  ) : <span />}
                  <span className="text-xs text-gray-400">{formatDate(p.created_at)}</span>
                </div>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* ── New Patient Modal ── */}
      {showCreate && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/30 backdrop-blur-sm"
          onClick={(e) => { if (e.target === e.currentTarget) closeModal(); }}
        >
          <div className="w-full max-w-sm bg-white rounded-2xl shadow-xl border border-gray-100 overflow-hidden">
            {/* Modal header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
              <h2 className="text-base font-bold text-gray-900">New Patient</h2>
              <button
                onClick={closeModal}
                className="w-7 h-7 rounded-lg flex items-center justify-center text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-all"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Modal body */}
            <form onSubmit={handleCreate} className="px-6 py-5 space-y-4">
              <div className="space-y-1.5">
                <label className="block text-sm font-semibold text-gray-800">
                  Full name <span className="text-red-500">*</span>
                </label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Rahul Verma"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  autoFocus
                />
              </div>

              <div className="flex gap-3">
                <div className="w-28 flex-shrink-0 space-y-1.5">
                  <label className="block text-sm font-semibold text-gray-800">
                    Age <span className="text-red-500">*</span>
                  </label>
                  <input
                    type="number"
                    className="input-field text-center"
                    placeholder="—"
                    min={1} max={120}
                    value={createAge}
                    onChange={(e) => setCreateAge(e.target.value)}
                  />
                </div>
                <div className="flex-1 space-y-1.5">
                  <label className="block text-sm font-semibold text-gray-800">Gender</label>
                  <div className="flex gap-1.5 h-[46px]">
                    {["Male", "Female", "Other"].map((g) => (
                      <button
                        key={g}
                        type="button"
                        onClick={() => setCreateGender(createGender === g ? "" : g)}
                        className={`flex-1 rounded-xl border text-xs font-semibold transition-all ${
                          createGender === g
                            ? "border-brand bg-brand-light text-brand"
                            : "border-gray-200 bg-gray-50 text-gray-500 hover:border-gray-300"
                        }`}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="block text-sm font-semibold text-gray-800">
                  Phone <span className="text-gray-400 font-normal">(optional)</span>
                </label>
                <input
                  type="tel"
                  className="input-field"
                  placeholder="+91 98765 43210"
                  value={createPhone}
                  onChange={(e) => setCreatePhone(e.target.value)}
                />
              </div>

              {createError && (
                <p className="text-red-600 text-sm font-medium">{createError}</p>
              )}

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={closeModal}
                  className="btn-secondary flex-1 py-2.5 text-sm"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="btn-primary flex-1 py-2.5 text-sm"
                >
                  {creating ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </main>
  );
}
