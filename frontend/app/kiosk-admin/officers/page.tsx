"use client";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import clsx from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  FileText,
  RotateCcw,
  Siren,
  Trash2,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { kioskAdminApi } from "@/lib/kiosk-admin-api";
import { getToken } from "@/lib/api";
import type { KioskAdminSession, KioskCentre } from "@/lib/kiosk-admin-types";
import {
  addCustomOfficer,
  DEPARTMENTS,
  isTicketCentre,
  LEVEL_DESIGNATION,
  officerLanes,
  readCustomOfficers,
  removeCustomOfficer,
  type CustomOfficer,
  type OfficerLane,
  type TicketLevel,
} from "@/lib/kiosk-tickets";
import { useKioskTickets } from "@/hooks/useKioskTickets";
import {
  CloseTicketModal,
  LEVEL_STYLE,
  LevelBadge,
  SlaText,
  TicketDetailsModal,
} from "@/components/kiosk-ticket-ui";

const LEVEL_TITLE: Record<TicketLevel, string> = {
  1: "L1 · First response",
  2: "L2 · Zonal escalation",
  3: "L3 · Commissioner's desk",
};

function OfficersContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const centreIdParam = searchParams.get("centre_id");

  const [sessions, setSessions] = useState<KioskAdminSession[]>([]);
  const [centre, setCentre] = useState<KioskCentre | null>(null);
  const [userRole, setUserRole] = useState("");
  const [adminName, setAdminName] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [custom, setCustom] = useState<CustomOfficer[]>([]);
  const [selectedOfficer, setSelectedOfficer] = useState<string | null>(null);
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const { tickets, applyOverride } = useKioskTickets(sessions);

  useEffect(() => {
    document.title = "Officers · Admin Panel";
    setCustom(readCustomOfficers());
  }, []);

  const load = useCallback(
    async (t: string, role: string) => {
      const cid = role === "super_admin" ? centreIdParam : null;
      const [centreRes, sessionsRes] = await Promise.all([
        kioskAdminApi.getCurrentCentre(t, cid),
        kioskAdminApi.listSessions(t, { centre_id: cid || undefined, limit: 200 }),
      ]);
      setCentre(centreRes);
      setSessions(sessionsRes.sessions);
    },
    [centreIdParam]
  );

  useEffect(() => {
    void boot();
    async function boot() {
      try {
        const t = await getToken();
        const payload = JSON.parse(atob(t.split(".")[1]));
        const role = payload.role;
        if (role !== "centre_admin" && role !== "super_admin") {
          router.push("/kiosk-admin/login");
          return;
        }
        setUserRole(role);
        setAdminName(payload.name || payload.email || "Admin");
        await load(t, role);
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "Failed to load";
        if (msg.includes("401") || msg === "refresh_failed") router.push("/kiosk-admin/login");
        else setError(msg);
      } finally {
        setLoading(false);
      }
    }
  }, [router, load]);

  const backHref = `/kiosk-admin${centreIdParam ? `?centre_id=${centreIdParam}` : ""}`;
  const lanes = useMemo(() => officerLanes(tickets, custom), [tickets, custom]);
  const byLevel = useMemo(
    () =>
      ([1, 2, 3] as TicketLevel[]).map((level) => ({
        level,
        lanes: lanes.filter((l) => l.officer.level === level),
      })),
    [lanes]
  );

  const selectedLane = lanes.find((l) => l.officer.id === selectedOfficer) ?? null;
  const officerTickets = useMemo(
    () => (selectedOfficer ? tickets.filter((t) => t.assignee.id === selectedOfficer) : []),
    [tickets, selectedOfficer]
  );

  const detailsTicket = tickets.find((t) => t.session.session_id === detailsId) ?? null;
  const closingTicket = tickets.find((t) => t.session.session_id === closingId) ?? null;

  const openSession = (sessionId: string) => {
    const q = userRole === "super_admin" && centreIdParam ? `?centre_id=${centreIdParam}` : "";
    router.push(`/kiosk-admin/sessions/${sessionId}${q}`);
  };

  if (loading) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-gray-50">
        <p className="text-sm text-gray-500">Loading…</p>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="sticky top-0 z-50 flex h-14 items-center justify-between border-b border-gray-100 bg-white px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => router.push(backHref)}
            className="text-sm text-gray-500 hover:text-amber-700"
          >
            ← Ticket desk
          </button>
          <span className="text-sm text-gray-600">{centre?.name}</span>
          {userRole === "super_admin" && (
            <span className="rounded-full bg-purple-100 px-2 py-1 text-xs font-semibold text-purple-700">
              Super Admin
            </span>
          )}
        </div>
        <div className="flex items-center gap-3">
          <span className="hidden items-center gap-1.5 text-xs text-gray-400 sm:flex">
            <Users size={13} />
            {lanes.length} officers
          </span>
          {isTicketCentre(centre) && (
            <button
              type="button"
              onClick={() => setShowAdd(true)}
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand px-3 py-1.5 text-xs font-semibold text-white hover:bg-brand-dark"
            >
              <UserPlus size={13} />
              Add officer
            </button>
          )}
        </div>
      </header>

      <div className="mx-auto max-w-7xl space-y-6 px-4 py-8">
        {error && (
          <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {!isTicketCentre(centre) ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-700">
            This kiosk does not use the officer ticket desk.{" "}
            <button
              type="button"
              onClick={() => router.push(backHref)}
              className="font-semibold underline"
            >
              Back to sessions
            </button>
          </div>
        ) : (
          <>
            <div>
              <h1 className="text-lg font-bold text-gray-900">Officers</h1>
              <p className="text-sm text-gray-500">
                The full ladder. A ticket sits with its L1 officer until the SLA runs out, then
                moves to L2 and finally L3. Click an officer to see their tickets.
              </p>
            </div>

            <div className="grid gap-4 lg:grid-cols-3">
              {byLevel.map(({ level, lanes: levelLanes }) => (
                <section key={level} className="space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <LevelBadge level={level} />
                      <h2 className="text-sm font-bold text-gray-700">{LEVEL_TITLE[level]}</h2>
                    </div>
                    <span className="text-xs text-gray-400">
                      {levelLanes.reduce((n, l) => n + l.open, 0)} open ·{" "}
                      {levelLanes.length} officers
                    </span>
                  </div>

                  <div className="max-h-[560px] space-y-2 overflow-y-auto pr-1">
                    {levelLanes.map((lane) => (
                      <OfficerCard
                        key={lane.officer.id}
                        lane={lane}
                        onClick={() => setSelectedOfficer(lane.officer.id)}
                      />
                    ))}
                  </div>
                </section>
              ))}
            </div>
          </>
        )}
      </div>

      {selectedLane && (
        <OfficerModal
          lane={selectedLane}
          tickets={officerTickets}
          onDismiss={() => setSelectedOfficer(null)}
          onDetails={setDetailsId}
          onClose={setClosingId}
          onReopen={(id) => applyOverride(id, null)}
          onRemove={
            selectedLane.custom
              ? () => {
                  setCustom(removeCustomOfficer(selectedLane.officer.id));
                  setSelectedOfficer(null);
                }
              : undefined
          }
        />
      )}

      {showAdd && (
        <AddOfficerModal
          onDismiss={() => setShowAdd(false)}
          onAdd={(officer) => {
            setCustom(addCustomOfficer(officer));
            setShowAdd(false);
          }}
        />
      )}

      {detailsTicket && (
        <TicketDetailsModal
          ticket={detailsTicket}
          onDismiss={() => setDetailsId(null)}
          onOpenSession={() => openSession(detailsTicket.session.session_id)}
          onCloseTicket={() => setClosingId(detailsTicket.session.session_id)}
          onReopen={() => applyOverride(detailsTicket.session.session_id, null)}
        />
      )}

      {closingTicket && (
        <CloseTicketModal
          ticket={closingTicket}
          currentUser={adminName}
          onDismiss={() => setClosingId(null)}
          onConfirm={(patch) => {
            applyOverride(closingTicket.session.session_id, patch);
            setClosingId(null);
            setDetailsId(null);
          }}
        />
      )}
    </main>
  );
}

function OfficerCard({ lane, onClick }: { lane: OfficerLane; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="w-full rounded-xl border border-gray-100 bg-white p-3 text-left transition-all hover:border-brand/40 hover:shadow-sm"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-gray-900">
            {lane.officer.name}
            {lane.custom && (
              <span className="ml-1.5 rounded bg-brand-light px-1.5 py-0.5 text-[10px] font-bold text-brand">
                added
              </span>
            )}
          </p>
          <p className="truncate text-[11px] text-gray-500">
            {LEVEL_DESIGNATION[lane.officer.level].en}
          </p>
          <p className="truncate text-[11px] text-gray-400">{lane.departmentLabel}</p>
        </div>
        <span
          className={clsx(
            "shrink-0 rounded-full border px-2 py-0.5 text-[11px] font-bold tabular-nums",
            lane.open > 0 ? LEVEL_STYLE[lane.officer.level] : "border-gray-200 text-gray-400"
          )}
        >
          {lane.open}
        </span>
      </div>
      <div className="mt-2 flex items-center gap-3 text-[11px] font-semibold">
        <span className={lane.open > 0 ? "text-blue-700" : "text-gray-400"}>{lane.open} open</span>
        {lane.overdue > 0 && (
          <span className="inline-flex items-center gap-1 text-red-600">
            <AlertTriangle size={10} />
            {lane.overdue} overdue
          </span>
        )}
        <span className="text-gray-400">{lane.closed} closed</span>
      </div>
    </button>
  );
}

function OfficerModal({
  lane,
  tickets,
  onDismiss,
  onDetails,
  onClose,
  onReopen,
  onRemove,
}: {
  lane: OfficerLane;
  tickets: ReturnType<typeof useKioskTickets>["tickets"];
  onDismiss: () => void;
  onDetails: (sessionId: string) => void;
  onClose: (sessionId: string) => void;
  onReopen: (sessionId: string) => void;
  onRemove?: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/40 px-4 py-10"
      onClick={onDismiss}
    >
      <div
        className="w-full max-w-3xl rounded-2xl bg-white shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3 border-b border-gray-100 px-6 py-4">
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-lg font-bold text-gray-900">{lane.officer.name}</h3>
              <LevelBadge level={lane.officer.level} />
              {lane.custom && (
                <span className="rounded bg-brand-light px-1.5 py-0.5 text-[10px] font-bold text-brand">
                  added
                </span>
              )}
            </div>
            <p className="mt-0.5 text-xs text-gray-500">
              {LEVEL_DESIGNATION[lane.officer.level].en} · {lane.departmentLabel}
            </p>
          </div>
          <button type="button" onClick={onDismiss} className="text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        <div className="grid grid-cols-4 gap-3 border-b border-gray-100 px-6 py-4">
          <Stat label="Assigned" value={lane.total} />
          <Stat label="Open" value={lane.open} className="text-blue-700" />
          <Stat label="Overdue" value={lane.overdue} className="text-red-600" />
          <Stat label="Closed" value={lane.closed} className="text-green-700" />
        </div>

        <div className="max-h-[50vh] overflow-y-auto">
          {tickets.length === 0 ? (
            <p className="px-6 py-10 text-center text-sm text-gray-400">
              No tickets are assigned to this officer right now.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b border-gray-100 bg-gray-50">
                <tr>
                  <th className="px-6 py-2.5 text-left font-semibold text-gray-500">Ticket</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-gray-500">Ward</th>
                  <th className="px-4 py-2.5 text-left font-semibold text-gray-500">SLA</th>
                  <th className="px-6 py-2.5 text-right font-semibold text-gray-500">Action</th>
                </tr>
              </thead>
              <tbody>
                {tickets.map((t) => {
                  const id = t.session.session_id;
                  return (
                    <tr
                      key={id}
                      className={clsx(
                        "border-b border-gray-50 last:border-0",
                        t.closed && "bg-gray-50/60",
                        !t.closed && t.overdue && "bg-red-50/40"
                      )}
                    >
                      <td className="px-6 py-3">
                        <button
                          type="button"
                          onClick={() => onDetails(id)}
                          className="flex items-center gap-1.5 font-mono text-amber-800 hover:underline"
                        >
                          {t.urgent && !t.closed && <Siren size={13} className="text-red-500" />}
                          {t.ticketNo}
                        </button>
                        <p className="mt-0.5 max-w-xs truncate text-xs text-gray-500">{t.summary}</p>
                      </td>
                      <td className="px-4 py-3 text-gray-600">{t.ward ?? "—"}</td>
                      <td className="px-4 py-3">
                        <SlaText ticket={t} />
                      </td>
                      <td className="px-6 py-3">
                        <div className="flex justify-end gap-2">
                          <button
                            type="button"
                            onClick={() => onDetails(id)}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50"
                          >
                            <FileText size={12} />
                            Details
                          </button>
                          {t.closed ? (
                            <button
                              type="button"
                              onClick={() => onReopen(id)}
                              className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                            >
                              <RotateCcw size={12} />
                              Reopen
                            </button>
                          ) : (
                            <button
                              type="button"
                              onClick={() => onClose(id)}
                              className="inline-flex items-center gap-1 rounded-lg bg-green-600 px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-green-700"
                            >
                              <CheckCircle2 size={12} />
                              Mark closed
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 border-t border-gray-100 px-6 py-4">
          {onRemove ? (
            <button
              type="button"
              onClick={onRemove}
              className="inline-flex items-center gap-1.5 text-xs font-semibold text-red-600 hover:underline"
            >
              <Trash2 size={13} />
              Remove officer
            </button>
          ) : (
            <span className="text-xs text-gray-400">Standing GMC roster</span>
          )}
          <button type="button" onClick={onDismiss} className="btn-secondary text-sm py-2 px-4">
            Close
          </button>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, className }: { label: string; value: number; className?: string }) {
  return (
    <div className="rounded-xl border border-gray-100 px-3 py-2 text-center">
      <p className={clsx("text-lg font-bold tabular-nums", className ?? "text-gray-900")}>{value}</p>
      <p className="text-[11px] text-gray-400">{label}</p>
    </div>
  );
}

function AddOfficerModal({
  onDismiss,
  onAdd,
}: {
  onDismiss: () => void;
  onAdd: (officer: { name: string; level: TicketLevel; department: string }) => void;
}) {
  const [name, setName] = useState("");
  const [level, setLevel] = useState<TicketLevel>(1);
  const [department, setDepartment] = useState(DEPARTMENTS[0].key);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md space-y-4 rounded-2xl bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between">
          <h3 className="text-base font-bold text-gray-900">Add officer</h3>
          <button type="button" onClick={onDismiss} className="text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-gray-500">Name</label>
          <input
            className="input-field"
            placeholder="e.g. R. K. Sharma"
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-gray-500">Level</label>
          <div className="inline-flex gap-1 rounded-xl bg-gray-100 p-1">
            {([1, 2, 3] as TicketLevel[]).map((l) => (
              <button
                key={l}
                type="button"
                onClick={() => setLevel(l)}
                className={clsx(
                  "rounded-lg px-4 py-1.5 text-xs font-semibold transition-all",
                  level === l ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-800"
                )}
              >
                L{l}
              </button>
            ))}
          </div>
          <p className="text-[11px] text-gray-400">{LEVEL_DESIGNATION[level].en}</p>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-gray-500">Department</label>
          <select
            className="input-field"
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
          >
            {DEPARTMENTS.map((d) => (
              <option key={d.key} value={d.key}>
                {d.label}
              </option>
            ))}
          </select>
        </div>

        <p className="text-xs text-gray-400">
          New officers join the ladder for their wing. Tickets already in flight keep the officer
          they were routed to.
        </p>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onDismiss} className="btn-secondary text-sm py-2 px-4">
            Cancel
          </button>
          <button
            type="button"
            disabled={!name.trim()}
            onClick={() => onAdd({ name: name.trim(), level, department })}
            className="btn-primary text-sm py-2 px-4"
          >
            Add officer
          </button>
        </div>
      </div>
    </div>
  );
}

export default function KioskAdminOfficersPage() {
  return (
    <Suspense
      fallback={
        <main className="flex min-h-screen items-center justify-center bg-gray-50">
          <p className="text-sm text-gray-500">Loading…</p>
        </main>
      }
    >
      <OfficersContent />
    </Suspense>
  );
}
