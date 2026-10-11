"use client";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { KioskAdminSession } from "@/lib/kiosk-admin-types";
import {
  buildTicket,
  readOverrides,
  writeOverride,
  type OverrideStore,
  type Ticket,
  type TicketOverride,
} from "@/lib/kiosk-tickets";

/**
 * Derives tickets from kiosk sessions and keeps the SLA clock ticking.
 * Shared by the ticket desk and the officers page so a ticket closed in one
 * place shows up closed in the other.
 */
export function useKioskTickets(sessions: KioskAdminSession[]): {
  tickets: Ticket[];
  applyOverride: (sessionId: string, patch: TicketOverride | null) => void;
  ready: boolean;
} {
  const [overrides, setOverrides] = useState<OverrideStore>({});
  const [now, setNow] = useState(() => Date.now());
  const [ready, setReady] = useState(false);

  // localStorage is only readable after mount, so overrides land on the second
  // render — `ready` lets callers hold off instead of flashing wrong state.
  useEffect(() => {
    setOverrides(readOverrides());
    setReady(true);
    const id = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(id);
  }, []);

  const tickets = useMemo(
    () =>
      sessions
        .map((s) => buildTicket(s, overrides[s.session_id], now))
        .sort((a, b) => {
          if (a.closed !== b.closed) return a.closed ? 1 : -1;
          if (a.level !== b.level) return b.level - a.level;
          return a.msRemaining - b.msRemaining;
        }),
    [sessions, overrides, now]
  );

  const applyOverride = useCallback((sessionId: string, patch: TicketOverride | null) => {
    setOverrides(writeOverride(sessionId, patch));
    setNow(Date.now());
  }, []);

  return { tickets, applyOverride, ready };
}
