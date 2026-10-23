"use client";
import { useMemo, useState } from "react";
import clsx from "clsx";
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardList,
  FileText,
  RotateCcw,
  Siren,
} from "lucide-react";
import type { KioskAdminSession } from "@/lib/kiosk-admin-types";
import { LEVEL_DESIGNATION, type Ticket, type TicketLevel } from "@/lib/kiosk-tickets";
import { useKioskTickets } from "@/hooks/useKioskTickets";
import {
  CloseTicketModal,
  LevelBadge,
  SlaText,
  TicketDetailsModal,
} from "@/components/kiosk-ticket-ui";

type LevelTab = "all" | 1 | 2 | 3;
type StatusTab = "open" | "escalated" | "overdue" | "closed" | "all";

const STATUS_TABS: Array<{ key: StatusTab; label: string }> = [
  { key: "open", label: "Open" },
  { key: "escalated", label: "Escalated" },
  { key: "overdue", label: "Overdue" },
  { key: "closed", label: "Closed" },
  { key: "all", label: "All" },
];

function matchesStatus(t: Ticket, status: StatusTab): boolean {
  if (status === "open") return !t.closed;
  if (status === "escalated") return !t.closed && t.level > 1;
  if (status === "overdue") return !t.closed && t.overdue;
  if (status === "closed") return t.closed;
  return true;
}

function DeskStat({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
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
      <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <p className={clsx("mt-1 text-2xl font-bold", color ? colors[color] : "text-gray-900")}>
        {value}
      </p>
    </div>
  );
}

/** Segmented control — one row of pills with live counts. */
function Segmented<T extends string | number>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: Array<{ key: T; label: string; count: number; dot?: string }>;
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <div className="space-y-1.5">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</p>
      <div className="inline-flex flex-wrap gap-1 rounded-xl bg-gray-100 p-1">
        {options.map((o) => {
          const active = o.key === value;
          return (
            <button
              key={String(o.key)}
              type="button"
              onClick={() => onChange(o.key)}
              className={clsx(
                "inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all",
                active
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-500 hover:text-gray-800 disabled:opacity-40"
              )}
            >
              {o.dot && <span className={clsx("h-1.5 w-1.5 rounded-full", o.dot)} />}
              {o.label}
              <span
                className={clsx(
                  "rounded-md px-1.5 py-0.5 text-[10px] font-bold tabular-nums",
                  active ? "bg-gray-100 text-gray-700" : "bg-white/70 text-gray-400"
                )}
              >
                {o.count}
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function KioskTicketDesk({
  sessions,
  currentUser,
  onOpenSession,
}: {
  sessions: KioskAdminSession[];
  currentUser: string;
  onOpenSession: (sessionId: string) => void;
}) {
  const { tickets, applyOverride } = useKioskTickets(sessions);
  const [levelTab, setLevelTab] = useState<LevelTab>("all");
  const [statusTab, setStatusTab] = useState<StatusTab>("open");
  const [detailsId, setDetailsId] = useState<string | null>(null);
  const [closingId, setClosingId] = useState<string | null>(null);

  const counts = useMemo(() => {
    const open = tickets.filter((t) => !t.closed);
    return {
      total: tickets.length,
      open: open.length,
      escalated: open.filter((t) => t.level > 1).length,
      overdue: open.filter((t) => t.overdue).length,
      closed: tickets.length - open.length,
    };
  }, [tickets]);

  // Each control counts what the *other* control currently allows, so the
  // numbers always match what clicking it would actually show.
  const levelOptions = useMemo(() => {
    const inStatus = tickets.filter((t) => matchesStatus(t, statusTab));
    return [
      { key: "all" as LevelTab, label: "All levels", count: inStatus.length },
      ...([1, 2, 3] as TicketLevel[]).map((lvl) => ({
        key: lvl as LevelTab,
        label: `L${lvl}`,
        count: inStatus.filter((t) => t.level === lvl).length,
        dot: lvl === 1 ? "bg-blue-500" : lvl === 2 ? "bg-amber-500" : "bg-red-500",
      })),
    ];
  }, [tickets, statusTab]);

  const statusOptions = useMemo(() => {
    const inLevel = tickets.filter((t) => levelTab === "all" || t.level === levelTab);
    return STATUS_TABS.map((s) => ({
      key: s.key,
      label: s.label,
      count: inLevel.filter((t) => matchesStatus(t, s.key)).length,
    }));
  }, [tickets, levelTab]);

  const filtered = useMemo(
    () =>
      tickets.filter(
        (t) => (levelTab === "all" || t.level === levelTab) && matchesStatus(t, statusTab)
      ),
    [tickets, levelTab, statusTab]
  );

  const detailsTicket = tickets.find((t) => t.session.session_id === detailsId) ?? null;
  const closingTicket = tickets.find((t) => t.session.session_id === closingId) ?? null;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        <DeskStat label="Tickets" value={counts.total} />
        <DeskStat label="Open" value={counts.open} color="blue" />
        <DeskStat label="Escalated" value={counts.escalated} color="amber" />
        <DeskStat label="Overdue" value={counts.overdue} color="red" />
        <DeskStat label="Closed" value={counts.closed} color="green" />
      </div>

      <div className="card flex flex-wrap items-end justify-between gap-x-8 gap-y-4 py-4">
        <Segmented label="Escalation level" options={levelOptions} value={levelTab} onChange={setLevelTab} />
        <Segmented label="Ticket status" options={statusOptions} value={statusTab} onChange={setStatusTab} />
        <div className="ml-auto flex items-center gap-3 pb-1.5">
          <span className="text-xs text-gray-400">
            Showing <span className="font-semibold text-gray-700">{filtered.length}</span> of{" "}
            {tickets.length}
          </span>
          {(levelTab !== "all" || statusTab !== "open") && (
            <button
              type="button"
              onClick={() => {
                setLevelTab("all");
                setStatusTab("open");
              }}
              className="text-xs font-semibold text-brand hover:underline"
            >
              Reset
            </button>
          )}
        </div>
      </div>

      <div className="card overflow-x-auto p-0">
        <table className="w-full min-w-[920px] text-sm">
          <thead className="border-b border-gray-100 bg-gray-50">
            <tr>
              <th className="px-5 py-3 text-left font-semibold text-gray-500">Ticket</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-500">Department</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-500">Assigned officer</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-500">Level</th>
              <th className="px-4 py-3 text-left font-semibold text-gray-500">SLA</th>
              <th className="px-5 py-3 text-right font-semibold text-gray-500">Action</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-4 py-12 text-center text-gray-400">
                  <ClipboardList size={22} className="mx-auto mb-2 text-gray-300" />
                  No tickets match this filter.
                </td>
              </tr>
            ) : (
              filtered.map((t) => {
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
                    <td className="px-5 py-3">
                      <button
                        type="button"
                        onClick={() => setDetailsId(id)}
                        className="flex items-center gap-1.5 font-mono text-amber-800 hover:underline"
                      >
                        {t.urgent && !t.closed && <Siren size={13} className="text-red-500" />}
                        {t.ticketNo}
                      </button>
                      <p className="mt-0.5 max-w-sm truncate text-xs text-gray-500">{t.summary}</p>
                    </td>
                    <td className="px-4 py-3 text-gray-700">
                      {t.department.label}
                      {t.ward && <p className="text-xs text-gray-400">Ward {t.ward}</p>}
                    </td>
                    <td className="px-4 py-3">
                      <p className="text-gray-800">{t.assignee.name}</p>
                      <p className="text-xs text-gray-400">
                        {LEVEL_DESIGNATION[t.assignee.level].en}
                      </p>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <LevelBadge level={t.level} />
                        {t.level > 1 && !t.closed && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                            <AlertTriangle size={10} />
                            Escalated
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <SlaText ticket={t} />
                      <p className="text-[11px] text-gray-400">
                        {t.slaHours}h per level{t.urgent ? " · urgent" : ""}
                      </p>
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex justify-end gap-2">
                        <button
                          type="button"
                          onClick={() => setDetailsId(id)}
                          className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-gray-700 hover:bg-gray-50"
                        >
                          <FileText size={12} />
                          Details
                        </button>
                        {t.closed ? (
                          <button
                            type="button"
                            onClick={() => applyOverride(id, null)}
                            className="inline-flex items-center gap-1 rounded-lg border border-gray-200 px-2.5 py-1.5 text-xs font-semibold text-gray-600 hover:bg-gray-50"
                          >
                            <RotateCcw size={12} />
                            Reopen
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => setClosingId(id)}
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
              })
            )}
          </tbody>
        </table>
      </div>

      {/* <p className="text-xs text-gray-400">
        Tickets escalate on their own: each officer gets their department SLA to resolve, after
        which the ticket moves up the ladder (L1 {"→"} L2 {"→"} L3). Urgent grievances run on half
        the clock.
      </p> */}

      {detailsTicket && (
        <TicketDetailsModal
          ticket={detailsTicket}
          onDismiss={() => setDetailsId(null)}
          onOpenSession={() => onOpenSession(detailsTicket.session.session_id)}
          onCloseTicket={() => setClosingId(detailsTicket.session.session_id)}
          onReopen={() => applyOverride(detailsTicket.session.session_id, null)}
        />
      )}

      {closingTicket && (
        <CloseTicketModal
          ticket={closingTicket}
          currentUser={currentUser}
          onDismiss={() => setClosingId(null)}
          onConfirm={(patch) => {
            applyOverride(closingTicket.session.session_id, patch);
            setClosingId(null);
            setDetailsId(null);
          }}
        />
      )}
    </div>
  );
}
