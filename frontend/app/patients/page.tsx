"use client";
import { useRouter } from "next/navigation";
import { useState, useEffect, useCallback } from "react";
import { UserPlus, Search, LogOut, Users, ChevronRight, User } from "lucide-react";
import { api, getToken } from "@/lib/api";
import { getUser, type User as AuthUser } from "@/lib/auth";
import type { Patient } from "@/lib/types";

const GENDER_COLORS: Record<string, string> = {
  Male: "bg-blue-100 text-blue-700",
  Female: "bg-pink-100 text-pink-700",
  Other: "bg-purple-100 text-purple-700",
};

const AVATAR_COLORS = [
  "from-indigo-500 to-violet-500",
  "from-cyan-500 to-blue-500",
  "from-emerald-500 to-teal-500",
  "from-rose-500 to-pink-500",
  "from-amber-500 to-orange-500",
];

function avatarColor(name: string): string {
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) & 0xfffff;
  return AVATAR_COLORS[h % AVATAR_COLORS.length];
}

function initials(name: string): string {
  return name
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
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

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createName.trim()) { setCreateError("Name is required."); return; }
    if (!createAge || isNaN(Number(createAge)) || Number(createAge) < 1) {
      setCreateError("Valid age is required.");
      return;
    }
    setCreateError("");
    setCreating(true);
    try {
      const patient = await api.createPatient(
        createName.trim(),
        Number(createAge),
        createGender || undefined,
        createPhone.trim() || undefined,
      );
      setPatients((p) => [patient, ...p]);
      setShowCreate(false);
      setCreateName(""); setCreateAge(""); setCreateGender(""); setCreatePhone("");
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
    <main className="min-h-screen bg-[#0a0f1e]">
      {/* Header */}
      <div className="sticky top-0 z-30 bg-[#0a0f1e]/90 backdrop-blur border-b border-white/5 px-4 py-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center">
            <span className="text-white text-xs font-bold">K</span>
          </div>
          <span className="text-white font-semibold text-sm">kuvaka Clinical AI</span>
        </div>
        <div className="flex items-center gap-3">
          {authUser && <span className="text-xs text-slate-400 hidden sm:block">{authUser.name}</span>}
          <button
            onClick={handleLogout}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white border border-white/10 rounded-full px-3 py-1.5 transition-colors"
          >
            <LogOut className="w-3.5 h-3.5" />
            Sign out
          </button>
        </div>
      </div>

      <div className="max-w-4xl mx-auto px-4 py-8">
        {/* Page title */}
        <div className="flex items-center justify-between mb-6">
          <div className="flex items-center gap-2">
            <Users className="w-5 h-5 text-indigo-400" />
            <h1 className="text-xl font-bold text-white">Your Patients</h1>
            {patients.length > 0 && (
              <span className="text-xs bg-white/10 text-slate-300 rounded-full px-2 py-0.5">
                {patients.length}
              </span>
            )}
          </div>
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-1.5 bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold px-4 py-2 rounded-xl transition-colors"
          >
            <UserPlus className="w-4 h-4" />
            New Patient
          </button>
        </div>

        {/* Search */}
        {patients.length > 0 && (
          <div className="relative mb-6">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
            <input
              type="text"
              placeholder="Search patients…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-white/5 border border-white/10 text-white placeholder-slate-500 rounded-xl pl-9 pr-4 py-2.5 text-sm focus:outline-none focus:border-indigo-400 transition-colors"
            />
          </div>
        )}

        {/* Patient grid */}
        {filtered.length === 0 && !showCreate ? (
          <div className="text-center py-20">
            <div className="w-16 h-16 rounded-2xl bg-white/5 flex items-center justify-center mx-auto mb-4">
              <User className="w-8 h-8 text-slate-600" />
            </div>
            <p className="text-slate-400 text-sm mb-1">
              {search ? "No patients match your search." : "No patients yet."}
            </p>
            {!search && (
              <p className="text-slate-600 text-xs">Create your first patient to begin a consultation.</p>
            )}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {filtered.map((p) => (
              <button
                key={p.patient_id}
                onClick={() => router.push(`/patients/${p.patient_id}`)}
                className="group text-left bg-white/5 hover:bg-white/10 border border-white/10 hover:border-indigo-400/40 rounded-2xl p-5 transition-all duration-200"
              >
                <div className="flex items-start gap-3 mb-3">
                  <div
                    className={`w-11 h-11 rounded-xl bg-gradient-to-br ${avatarColor(p.name)} flex items-center justify-center text-white font-bold text-sm flex-shrink-0`}
                  >
                    {initials(p.name)}
                  </div>
                  <div className="flex-1 min-w-0">
                    <p className="text-white font-semibold text-sm truncate group-hover:text-indigo-300 transition-colors">
                      {p.name}
                    </p>
                    <p className="text-slate-400 text-xs mt-0.5">
                      {p.age} yrs
                      {p.gender && ` · ${p.gender}`}
                    </p>
                  </div>
                  <ChevronRight className="w-4 h-4 text-slate-600 group-hover:text-indigo-400 transition-colors mt-0.5 flex-shrink-0" />
                </div>
                {p.gender && (
                  <span className={`inline-block text-xs font-medium px-2 py-0.5 rounded-full ${GENDER_COLORS[p.gender] ?? "bg-slate-100 text-slate-600"}`}>
                    {p.gender}
                  </span>
                )}
                <p className="text-slate-600 text-xs mt-2">
                  Registered {formatDate(p.created_at)}
                </p>
              </button>
            ))}
          </div>
        )}
      </div>

      {/* Create patient modal */}
      {showCreate && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm">
          <div className="w-full max-w-sm bg-[#0f1629] border border-white/10 rounded-2xl p-6 shadow-2xl">
            <h2 className="text-white font-bold text-lg mb-5">New Patient</h2>
            <form onSubmit={handleCreate} className="space-y-4">
              <div>
                <label className="text-xs font-semibold text-slate-400 block mb-1.5">Full name <span className="text-red-400">*</span></label>
                <input
                  type="text"
                  className="w-full bg-white/5 border border-white/10 text-white placeholder-slate-500 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-indigo-400 transition-colors"
                  placeholder="e.g. Rahul Verma"
                  value={createName}
                  onChange={(e) => setCreateName(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="flex gap-3">
                <div className="w-28 flex-shrink-0">
                  <label className="text-xs font-semibold text-slate-400 block mb-1.5">Age <span className="text-red-400">*</span></label>
                  <input
                    type="number"
                    className="w-full bg-white/5 border border-white/10 text-white placeholder-slate-500 rounded-xl px-3 py-2.5 text-sm text-center focus:outline-none focus:border-indigo-400 transition-colors"
                    placeholder="—"
                    min={1} max={120}
                    value={createAge}
                    onChange={(e) => setCreateAge(e.target.value)}
                  />
                </div>
                <div className="flex-1">
                  <label className="text-xs font-semibold text-slate-400 block mb-1.5">Gender</label>
                  <div className="flex gap-1.5">
                    {["Male", "Female", "Other"].map((g) => (
                      <button
                        key={g}
                        type="button"
                        onClick={() => setCreateGender(createGender === g ? "" : g)}
                        className={`flex-1 py-2 rounded-lg border text-xs font-semibold transition-all ${
                          createGender === g
                            ? "border-indigo-400 bg-indigo-400/10 text-indigo-300"
                            : "border-white/10 text-slate-400 hover:border-white/20"
                        }`}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div>
                <label className="text-xs font-semibold text-slate-400 block mb-1.5">Phone (optional)</label>
                <input
                  type="tel"
                  className="w-full bg-white/5 border border-white/10 text-white placeholder-slate-500 rounded-xl px-3 py-2.5 text-sm focus:outline-none focus:border-indigo-400 transition-colors"
                  placeholder="+91 98765 43210"
                  value={createPhone}
                  onChange={(e) => setCreatePhone(e.target.value)}
                />
              </div>

              {createError && (
                <p className="text-red-400 text-xs">{createError}</p>
              )}

              <div className="flex gap-3 pt-1">
                <button
                  type="button"
                  onClick={() => { setShowCreate(false); setCreateError(""); }}
                  className="flex-1 py-2.5 rounded-xl border border-white/10 text-slate-400 hover:text-white text-sm font-semibold transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="flex-1 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold transition-colors disabled:opacity-60"
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
