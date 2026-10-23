"use client";
import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, ExternalLink, RotateCcw, Siren, X } from "lucide-react";
import {
  formatDuration,
  LEVEL_DESIGNATION,
  slaLabel,
  type Ticket,
  type TicketLevel,
  type TicketOverride,
} from "@/lib/kiosk-tickets";

export const LEVEL_STYLE: Record<TicketLevel, string> = {
  1: "bg-blue-50 text-blue-700 border-blue-200",
  2: "bg-amber-50 text-amber-700 border-amber-200",
  3: "bg-red-50 text-red-700 border-red-200",
};

export function LevelBadge({ level, className }: { level: TicketLevel; className?: string }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-bold",
        LEVEL_STYLE[level],
        className
      )}
    >
      L{level}
    </span>
  );
}

export function istTime(ms: number): string {
  return new Date(ms).toLocaleString("en-IN", {
    timeZone: "Asia/Kolkata",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function SlaText({ ticket }: { ticket: Ticket }) {
  return (
    <span
      className={clsx(
        "text-xs font-semibold",
        ticket.closed ? "text-green-700" : ticket.overdue ? "text-red-600" : "text-gray-600"
      )}
    >
      {slaLabel(ticket)}
    </span>
  );
}

function text(value: unknown): string | null {
  if (value === null || value === undefined) return null;
  if (typeof value === "boolean") return value ? "Yes" : "No";
  const s = String(value).trim();
  return s && s !== "null" ? s : null;
}

function addressLine(addr: unknown): string | null {
  if (!addr || typeof addr !== "object") return null;
  const a = addr as Record<string, unknown>;
  const parts = [a.house, a.street, a.village_mohalla, a.gp_ward && `Ward ${a.gp_ward}`, a.landmark, a.pin_code]
    .map(text)
    .filter(Boolean);
  return parts.length ? parts.join(", ") : null;
}

function Field({ label, value }: { label: string; value: string | null }) {
  if (!value) return null;
  return (
    <div>
      <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-sm text-gray-800 mt-0.5">{value}</p>
    </div>
  );
}

/** Full case file for one ticket — complainant, grievance, assignment, trail. */
export function TicketDetailsModal({
  ticket,
  onDismiss,
  onOpenSession,
  onCloseTicket,
  onReopen,
}: {
  ticket: Ticket;
  onDismiss: () => void;
  onOpenSession: () => void;
  onCloseTicket: () => void;
  onReopen: () => void;
}) {
  const g = (ticket.session.grievance ?? {}) as Record<string, unknown>;

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
              {ticket.urgent && !ticket.closed && <Siren size={15} className="text-red-500" />}
              <p className="font-mono text-lg font-bold text-amber-800">{ticket.ticketNo}</p>
              <LevelBadge level={ticket.level} />
              {ticket.closed && (
                <span className="rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-700">
                  Closed
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {ticket.department.label} · filed {ticket.session.started_at_ist || "—"}
            </p>
          </div>
          <button type="button" onClick={onDismiss} className="text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>

        <div className="space-y-5 px-6 py-5">
          <div className="rounded-xl border border-gray-100 bg-gray-50 px-4 py-3">
            <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide">
              Grievance
            </p>
            <p className="mt-1 text-sm text-gray-900">{ticket.summary}</p>
            {text(g.verbatim_problem) && text(g.verbatim_problem) !== ticket.summary && (
              <p className="mt-2 text-xs italic text-gray-500">
                In their words: {text(g.verbatim_problem)}
              </p>
            )}
          </div>

          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            <Field label="Complainant" value={text(g.full_name)} />
            <Field label="Father / Guardian" value={text(g.father_guardian_name)} />
            <Field label="Phone" value={text(ticket.session.phone)} />
            <Field label="Category" value={text(g.category)} />
            <Field label="Sub-category" value={text(g.sub_category)} />
            <Field label="Urgency" value={text(g.urgency) ?? "normal"} />
            <Field label="Since when" value={text(g.since_when)} />
            <Field label="People affected" value={text(g.affected_count)} />
            <Field label="Prior action" value={text(g.prior_action)} />
            <Field label="Desired outcome" value={text(g.desired_outcome)} />
            <Field label="Complaint location" value={addressLine(g.complaint_address)} />
            <Field label="Home address" value={addressLine(g.residential_address)} />
            <Field
              label="Documents"
              value={
                Array.isArray(g.documents_to_attach_or_required) && g.documents_to_attach_or_required.length
                  ? (g.documents_to_attach_or_required as unknown[]).map(String).join(", ")
                  : null
              }
            />
            <Field
              label="Flags"
              value={Array.isArray(g.flags) && g.flags.length ? (g.flags as unknown[]).map(String).join(", ") : null}
            />
            <Field label="Session status" value={text(ticket.session.status)} />
          </div>

          <div className="grid gap-5 sm:grid-cols-2">
            <div>
              <p className="mb-2 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">
                Escalation ladder
              </p>
              <ol className="space-y-1.5">
                {ticket.ladder.map((o) => (
                  <li key={o.id} className="flex items-center gap-2 text-xs">
                    <LevelBadge level={o.level} />
                    <span
                      className={clsx(
                        o.level === ticket.level
                          ? "font-semibold text-gray-900"
                          : o.level < ticket.level
                            ? "text-gray-400 line-through"
                            : "text-gray-400"
                      )}
                    >
                      {o.name} · {LEVEL_DESIGNATION[o.level].en}
                    </span>
                    {o.level === ticket.level && !ticket.closed && (
                      <span className="text-[10px] font-semibold text-brand">holding now</span>
                    )}
                  </li>
                ))}
              </ol>
              <p className="mt-2 text-[11px] text-gray-400">
                {ticket.slaHours}h per level{ticket.urgent ? " · urgent, half clock" : ""}
              </p>
            </div>

            <div>
              <p className="mb-2 text-[11px] font-semibold text-gray-400 uppercase tracking-wide">
                Trail
              </p>
              <ul className="space-y-1.5 text-xs text-gray-600">
                <li>
                  Filed {ticket.session.started_at_ist || "—"} · assigned to {ticket.ladder[0].name}{" "}
                  (L1)
                </li>
                {ticket.escalations.map((e, i) => (
                  <li key={i} className="flex items-start gap-1.5 text-amber-700">
                    <AlertTriangle size={11} className="mt-0.5 shrink-0" />
                    <span>
                      L{e.fromLevel} → L{e.toLevel} at {istTime(e.at)} — {e.reason}
                    </span>
                  </li>
                ))}
                {ticket.closed && ticket.closedAt ? (
                  <li className="flex items-start gap-1.5 text-green-700">
                    <CheckCircle2 size={11} className="mt-0.5 shrink-0" />
                    <span>
                      Closed {istTime(new Date(ticket.closedAt).getTime())} by {ticket.closedBy}
                      {ticket.closureNote ? ` — ${ticket.closureNote}` : ""}
                    </span>
                  </li>
                ) : (
                  <li>
                    {ticket.dueAt
                      ? ticket.msRemaining >= 0
                        ? ticket.level < 3
                          ? `Escalates to L${ticket.level + 1} on ${istTime(ticket.dueAt)} (${formatDuration(ticket.msRemaining)} left)`
                          : `Final deadline ${istTime(ticket.dueAt)} (${formatDuration(ticket.msRemaining)} left)`
                        : `Past the final L3 deadline by ${formatDuration(ticket.msRemaining)}`
                      : "No filing time recorded."}
                  </li>
                )}
              </ul>
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-gray-100 px-6 py-4">
          <button
            type="button"
            onClick={onOpenSession}
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand hover:underline"
          >
            <ExternalLink size={13} />
            Open full session (transcript, document)
          </button>
          <div className="flex gap-2">
            <button type="button" onClick={onDismiss} className="btn-secondary text-sm py-2 px-4">
              Close
            </button>
            {ticket.closed ? (
              <button
                type="button"
                onClick={onReopen}
                className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-4 py-2 text-sm font-semibold text-gray-600 hover:bg-gray-50"
              >
                <RotateCcw size={14} />
                Reopen
              </button>
            ) : (
              <button
                type="button"
                onClick={onCloseTicket}
                className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700"
              >
                <CheckCircle2 size={14} />
                Mark closed
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

/** Closure dialog — the note is what the officer records as work done. */
export function CloseTicketModal({
  ticket,
  currentUser,
  onDismiss,
  onConfirm,
}: {
  ticket: Ticket;
  currentUser: string;
  onDismiss: () => void;
  onConfirm: (patch: TicketOverride) => void;
}) {
  const [note, setNote] = useState("");

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/40 px-4">
      <div className="w-full max-w-md space-y-4 rounded-2xl bg-white p-5 shadow-xl">
        <div className="flex items-start justify-between">
          <div>
            <h3 className="text-base font-bold text-gray-900">Close ticket</h3>
            <p className="mt-0.5 font-mono text-xs text-gray-500">{ticket.ticketNo}</p>
          </div>
          <button type="button" onClick={onDismiss} className="text-gray-400 hover:text-gray-700">
            <X size={18} />
          </button>
        </div>
        <div className="rounded-xl bg-gray-50 px-3 py-2 text-xs text-gray-600">
          Closing as <span className="font-semibold">{ticket.assignee.name}</span> (L{ticket.level} ·{" "}
          {ticket.department.label})
        </div>
        <div className="space-y-1">
          <label className="text-xs font-semibold uppercase text-gray-500">Resolution note</label>
          <textarea
            className="input-field min-h-[90px] resize-y"
            placeholder="What was done on the ground?"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
        </div>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onDismiss} className="btn-secondary text-sm py-2 px-4">
            Cancel
          </button>
          <button
            type="button"
            onClick={() =>
              onConfirm({
                closed_at: new Date().toISOString(),
                closed_by: `${ticket.assignee.name} (L${ticket.level}) · via ${currentUser}`,
                closure_note: note.trim() || "Resolved — no note recorded.",
              })
            }
            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700"
          >
            <CheckCircle2 size={14} />
            Mark closed
          </button>
        </div>
      </div>
    </div>
  );
}
