"use client";
import { useState } from "react";
import clsx from "clsx";
import { AlertTriangle, CheckCircle2, RotateCcw } from "lucide-react";
import type { KioskAdminSession } from "@/lib/kiosk-admin-types";
import { formatDuration, LEVEL_DESIGNATION } from "@/lib/kiosk-tickets";
import { useKioskTickets } from "@/hooks/useKioskTickets";
import { CloseTicketModal, istTime, LevelBadge, LEVEL_STYLE, SlaText } from "@/components/kiosk-ticket-ui";

/** Assignment + escalation strip shown on a Gwalior grievance session. */
export default function KioskTicketAssignment({
  session,
  currentUser,
}: {
  session: KioskAdminSession;
  currentUser: string;
}) {
  const { tickets, applyOverride, ready } = useKioskTickets([session]);
  const [closing, setClosing] = useState(false);

  // Closures live in localStorage, so hold the strip back until after hydration.
  if (!ready || tickets.length === 0) return null;
  const t = tickets[0];

  return (
    <div className="card space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-400">
            Assigned officer
          </p>
          <p className="mt-0.5 text-base font-bold text-gray-900">{t.assignee.name}</p>
          <p className="text-xs text-gray-500">
            {LEVEL_DESIGNATION[t.assignee.level].en} · {t.department.label}
            {t.ward ? ` · Ward ${t.ward}` : ""}
          </p>
        </div>
        <div className="space-y-1 text-right">
          <LevelBadge level={t.level} />
          <p>
            <SlaText ticket={t} />
          </p>
          <p className="text-[11px] text-gray-400">
            {t.slaHours}h per level{t.urgent ? " · urgent" : ""}
          </p>
        </div>
      </div>

      <ol className="flex flex-wrap items-center gap-2 text-xs">
        {t.ladder.map((o, i) => (
          <li key={o.id} className="flex items-center gap-2">
            {i > 0 && <span className="text-gray-300">→</span>}
            <span
              className={clsx(
                "rounded-full border px-2 py-0.5",
                o.level === t.level
                  ? `${LEVEL_STYLE[o.level]} font-semibold`
                  : "border-gray-200 text-gray-400"
              )}
            >
              L{o.level} {o.name}
            </span>
          </li>
        ))}
      </ol>

      {(t.escalations.length > 0 || t.closed) && (
        <ul className="space-y-1 border-t border-gray-100 pt-3 text-xs">
          {t.escalations.map((e, i) => (
            <li key={i} className="flex items-start gap-1.5 text-amber-700">
              <AlertTriangle size={12} className="mt-0.5 shrink-0" />
              <span>
                L{e.fromLevel} → L{e.toLevel} at {istTime(e.at)} — {e.reason}
              </span>
            </li>
          ))}
          {t.closed && t.closedAt && (
            <li className="flex items-start gap-1.5 text-green-700">
              <CheckCircle2 size={12} className="mt-0.5 shrink-0" />
              <span>
                Closed {istTime(new Date(t.closedAt).getTime())} by {t.closedBy}
                {t.closureNote ? ` — ${t.closureNote}` : ""}
              </span>
            </li>
          )}
        </ul>
      )}

      {!t.closed && t.dueAt && t.msRemaining >= 0 && (
        <p className="text-xs text-gray-500">
          {t.level < 3
            ? `Escalates to L${t.level + 1} on ${istTime(t.dueAt)} (${formatDuration(t.msRemaining)} left) if not closed.`
            : `Final deadline ${istTime(t.dueAt)} (${formatDuration(t.msRemaining)} left).`}
        </p>
      )}

      <div>
        {t.closed ? (
          <button
            type="button"
            onClick={() => applyOverride(session.session_id, null)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-2 text-xs font-semibold text-gray-600 hover:bg-gray-50"
          >
            <RotateCcw size={13} />
            Reopen ticket
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setClosing(true)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-green-600 px-3 py-2 text-xs font-semibold text-white hover:bg-green-700"
          >
            <CheckCircle2 size={13} />
            Mark closed
          </button>
        )}
      </div>

      {closing && (
        <CloseTicketModal
          ticket={t}
          currentUser={currentUser}
          onDismiss={() => setClosing(false)}
          onConfirm={(patch) => {
            applyOverride(session.session_id, patch);
            setClosing(false);
          }}
        />
      )}
    </div>
  );
}
