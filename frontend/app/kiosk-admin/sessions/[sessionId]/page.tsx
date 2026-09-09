"use client";
import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { kioskAdminApi } from "@/lib/kiosk-admin-api";
import type { KioskAdminSessionDetail, KioskCentre } from "@/lib/kiosk-admin-types";
import { getToken } from "@/lib/api";
import clsx from "clsx";

function formatAddress(addr: Record<string, unknown> | null | undefined): string {
  if (!addr) return "—";
  const parts = [
    addr.house,
    addr.street,
    addr.village_mohalla,
    addr.gp_ward,
    addr.tehsil,
    addr.block,
    addr.post_office,
    addr.pin_code,
    addr.landmark,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "—";
}

async function copyText(text: string) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    /* ignore */
  }
}

function printDocument(title: string, body: string) {
  const win = window.open("", "_blank", "noopener,noreferrer");
  if (!win) return;
  win.document.write(
    `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${title}</title>` +
      `<style>body{font-family:system-ui,sans-serif;padding:24px;white-space:pre-wrap;line-height:1.6}</style>` +
      `</head><body>${body.replace(/</g, "&lt;")}</body></html>`
  );
  win.document.close();
  win.focus();
  win.print();
}

export default function KioskAdminSessionPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;
  const centreIdParam = searchParams.get("centre_id");

  const [session, setSession] = useState<KioskAdminSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [userRole, setUserRole] = useState("");
  const [centres, setCentres] = useState<KioskCentre[]>([]);
  const [copied, setCopied] = useState("");

  useEffect(() => {
    document.title = "Admin Panel";
  }, []);

  const loadSession = useCallback(
    async (t: string, role: string) => {
      const centreId = role === "super_admin" ? centreIdParam : null;
      const sessionData = await kioskAdminApi.getSession(t, sessionId, centreId);
      setSession(sessionData);
      return sessionData;
    },
    [sessionId, centreIdParam]
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
        setUserRole(role);
        if (role === "super_admin") {
          await kioskAdminApi.listCentres(t).then((r) => setCentres(r.centres));
        }
        await loadSession(t, role);
      })
      .catch((e) => {
        if (e.message?.includes("401") || e.message === "refresh_failed") {
          router.push("/kiosk-admin/login");
        } else {
          setError(e.message);
        }
      })
      .finally(() => setLoading(false));
  }, [router, loadSession]);

  useEffect(() => {
    if (!session || session.status !== "active") return;
    let cancelled = false;
    const poll = async () => {
      try {
        const t = await getToken();
        const data = await loadSession(t, userRole);
        if (!cancelled && data.status === "active") {
          window.setTimeout(poll, 5000);
        }
      } catch {
        /* ignore poll errors */
      }
    };
    const timer = window.setTimeout(poll, 5000);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [session?.status, session?.session_id, userRole, loadSession]);

  const sessionCentre = centres.find((c) => c.centre_id === session?.centre_id);
  const isLearning = session?.centre_kind === "learning" || sessionCentre?.centre_kind === "learning";
  const g = session?.grievance as Record<string, unknown> | null | undefined;
  const lr = session?.learning_record;
  const printText =
    session?.print_document_text ||
    (typeof g?.print_document_text === "string" ? g.print_document_text : "") ||
    "";
  const transcriptEntries = session?.transcript ?? [];
  const transcriptPlain =
    session?.full_transcript ||
    transcriptEntries.map((e) => `${e.speaker}: ${e.text}`).join("\n");

  const handleCopy = async (key: string, text: string) => {
    await copyText(text);
    setCopied(key);
    window.setTimeout(() => setCopied(""), 2000);
  };

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500 text-sm">Loading…</p>
      </main>
    );
  }
  if (error) return <p className="p-8 text-red-600 text-sm">{error}</p>;
  if (!session) return null;

  const docTitle =
    g?.print_mode === "application_letter" || session.print_mode === "application_letter"
      ? "प्रार्थना पत्र"
      : "जानकारी पत्र";

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => router.push("/kiosk-admin")}
            className="text-sm text-gray-500 hover:text-amber-700"
          >
            ← Sessions
          </button>
          {userRole === "super_admin" && (
            <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs font-semibold rounded-full">
              Super Admin
            </span>
          )}
        </div>
        {(session.centre_name || sessionCentre) && (
          <span className="text-xs font-semibold text-gray-500">
            {session.centre_name || sessionCentre?.name}
          </span>
        )}
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <div className="text-center space-y-2">
          {isLearning ? (
            <p className="text-2xl font-bold text-pink-600">गुड्डी 🌸</p>
          ) : (
            session.complaint_number && (
              <p className="text-3xl font-mono font-bold text-amber-700 tracking-wide">
                {session.complaint_number}
              </p>
            )
          )}
          <p className="text-sm text-gray-500">
            {session.started_at_ist || "—"}
            {isLearning
              ? ` · ${session.learner_name || "—"} · ${session.lesson_topic || "—"}`
              : ` · Phone: ${session.phone || "—"}`}
            {!isLearning && session.session_type ? ` · ${session.session_type}` : ""}
            {!isLearning && session.print_mode ? ` · ${session.print_mode}` : ""}
          </p>
          <span
            className={clsx(
              "inline-block text-xs font-semibold px-2 py-1 rounded-full",
              session.status === "completed" && "bg-green-100 text-green-700",
              session.status === "partial" && "bg-amber-100 text-amber-700",
              session.status === "active" && "bg-blue-100 text-blue-700"
            )}
          >
            {session.status}
            {session.status === "active" ? " · live transcript updates" : ""}
          </span>
        </div>

        {lr && (
          <div className="bg-white rounded-2xl border border-pink-100 shadow-sm divide-y divide-gray-100">
            {[
              ["Summary", lr.friendly_summary],
              ["Topic", lr.topic || session.lesson_topic],
              ["Mood", lr.mood_start],
              ["Mode", lr.mode_used],
              ["Engagement", lr.engagement],
              ["Milestone", lr.milestone_signal],
              ["Flags", lr.flags !== "none" ? lr.flags : null],
              ["Next focus", lr.next_focus?.join(", ")],
              ["Note", lr.pronunciation_note],
            ].map(([label, value]) =>
              value ? (
                <div key={String(label)} className="px-5 py-4">
                  <p className="text-xs font-semibold text-gray-400 uppercase">{String(label)}</p>
                  <p className="text-gray-900 mt-1">{String(value)}</p>
                </div>
              ) : null
            )}
            {(lr.words_practiced?.length ?? 0) > 0 && (
              <div className="px-5 py-4">
                <p className="text-xs font-semibold text-gray-400 uppercase mb-2">Words</p>
                <div className="space-y-1">
                  {lr.words_practiced!.map((w, i) => (
                    <p key={i} className="text-sm text-gray-800">
                      {w.word} — {w.result}
                      {w.said_in_dialect ? " (dialect)" : ""}
                    </p>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {!isLearning && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-3">
            <div className="flex items-center justify-between gap-3">
              <h2 className="text-base font-bold text-gray-900">{docTitle}</h2>
              {printText.trim() && (
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleCopy("doc", printText)}
                    className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
                  >
                    {copied === "doc" ? "Copied" : "Copy"}
                  </button>
                  <button
                    type="button"
                    onClick={() => printDocument(docTitle, printText)}
                    className="text-xs px-3 py-1.5 rounded-lg border border-amber-200 text-amber-700 hover:bg-amber-50"
                  >
                    Print
                  </button>
                </div>
              )}
            </div>
            {printText.trim() ? (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-gray-900">
                {printText}
              </pre>
            ) : (
              <p className="text-sm text-gray-500">
                {session.status === "active"
                  ? "Document will appear here after the call ends and processing completes."
                  : "No printable document was generated for this session."}
              </p>
            )}
          </div>
        )}

        {g && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm divide-y divide-gray-100">
            {[
              ["Name", g.full_name],
              ["Father / Guardian", g.father_guardian_name],
              ["Category", g.category],
              ["Department", g.department_tag],
              ["Urgency", g.urgency],
              ["Problem", g.confirmed_summary || g.verbatim_problem],
              ["Since", g.since_when],
              ["Desired outcome", g.desired_outcome],
              ["Address", formatAddress(g.residential_address as Record<string, unknown>)],
            ].map(([label, value]) =>
              value ? (
                <div key={String(label)} className="px-5 py-4">
                  <p className="text-xs font-semibold text-gray-400 uppercase">{String(label)}</p>
                  <p className="text-gray-900 mt-1">{String(value)}</p>
                </div>
              ) : null
            )}
          </div>
        )}

        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-4">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-base font-bold text-gray-900">पूरी बातचीत</h2>
              <p className="text-xs text-gray-400 mt-0.5">
                {transcriptEntries.length > 0
                  ? `${transcriptEntries.length} turns recorded`
                  : "No transcript yet"}
              </p>
            </div>
            {transcriptPlain.trim() && (
              <button
                type="button"
                onClick={() => void handleCopy("transcript", transcriptPlain)}
                className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-600 hover:bg-gray-50"
              >
                {copied === "transcript" ? "Copied" : "Copy all"}
              </button>
            )}
          </div>
          {transcriptEntries.length > 0 ? (
            <div className="space-y-3 max-h-[28rem] overflow-y-auto">
              {transcriptEntries.map((entry, i) => {
                const isUser = entry.speaker === "user";
                return (
                  <div
                    key={i}
                    className={clsx(
                      "rounded-2xl p-4 border",
                      isUser ? "bg-amber-50 border-amber-100" : "bg-white border-gray-100"
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <p
                        className={clsx(
                          "text-xs font-medium",
                          isUser ? "text-amber-700" : "text-gray-400"
                        )}
                      >
                        {isUser ? (isLearning ? "बच्चा" : "आप") : isLearning ? "गुड्डी" : "AI सहायक"}
                      </p>
                      {entry.timestamp && (
                        <p className="text-[10px] text-gray-400">{entry.timestamp}</p>
                      )}
                    </div>
                    <p className="text-gray-800 leading-relaxed">{entry.text}</p>
                  </div>
                );
              })}
            </div>
          ) : transcriptPlain.trim() ? (
            <pre className="whitespace-pre-wrap text-sm text-gray-800 leading-relaxed">
              {transcriptPlain}
            </pre>
          ) : (
            <p className="text-sm text-gray-500">
              {session.status === "active"
                ? "Conversation will appear here as the citizen speaks."
                : "No conversation was captured for this session."}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
