"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { adminApi } from "@/lib/ticketing-api";
import type { TicketFlag } from "@/lib/ticketing-types";
import { getToken } from "@/lib/api";
import clsx from "clsx";

interface DetailSession {
  session_id: string;
  ticket_number: string | null;
  hospital_id: string;
  patient_id: string;
  phase: string;
  status: string;
  category: { key: string; label: string; source: string } | null;
  language: string;
  gender: string;
  turn_count: number;
  started_at_ist: string | null;
  ended_at_ist: string | null;
  deleted_at_ist: string | null;
  deleted_at: string | null;
  flags: TicketFlag[];
  qa_log: Array<{ question_id: string; question_text: string; answer: string }>;
  summary: Record<string, unknown> | null;
  patient: {
    patient_id: string;
    name: string | null;
    age: number | null;
    gender: string | null;
    phone: string;
  } | null;
}

export default function SessionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  const [session, setSession] = useState<DetailSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getToken()
      .then((t) => adminApi.getSession(t, sessionId))
      .then((s) => setSession(s as unknown as DetailSession))
      .catch((e) => {
        if (e.message?.includes("401") || e.message === "refresh_failed") {
          router.push("/login");
        } else {
          setError(e.message);
        }
      })
      .finally(() => setLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  if (loading) return <Spinner />;
  if (error) return <p className="p-8 text-red-600 text-sm">{error}</p>;
  if (!session) return null;

  const critical = session.flags.filter((f) => f.flag_type === "CRITICAL_RED_FLAG");
  const redFlags = session.flags.filter((f) => f.flag_type === "RED_FLAG");
  const others = session.flags.filter(
    (f) => f.flag_type !== "CRITICAL_RED_FLAG" && f.flag_type !== "RED_FLAG"
  );

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-6 h-14 flex items-center gap-3 sticky top-0 z-50">
        <button
          onClick={() => router.push("/admin")}
          className="text-sm text-gray-500 hover:text-brand transition-colors"
        >
          ← Sessions
        </button>
        <span className="text-gray-300">|</span>
        <span className="text-sm font-mono text-gray-400">{sessionId.slice(0, 12)}…</span>
      </header>

      <div className="max-w-3xl mx-auto px-4 py-8 space-y-6 fade-up">

        {/* Discarded banner */}
        {session.deleted_at && (
          <div className="bg-gray-100 border border-gray-200 rounded-xl px-4 py-3 text-sm text-gray-600">
            🗑️ This session was discarded by the patient on {session.deleted_at_ist || session.deleted_at}.
          </div>
        )}

        {/* Patient + meta */}
        <div className="card space-y-3">
          {/* Ticket number banner */}
          {session.ticket_number && (
            <div className="flex items-center justify-between pb-3 border-b border-gray-100">
              <p className="text-xs text-gray-400 uppercase tracking-wide">Ticket Number</p>
              <p className="text-2xl font-black font-mono text-brand tracking-tight">
                {session.ticket_number}
              </p>
            </div>
          )}

          <div className="flex items-start justify-between">
            <div>
              <h2 className="text-lg font-bold text-gray-900">
                {session.patient?.name || "Anonymous"}
              </h2>
              <div className="flex flex-wrap gap-2 mt-1.5">
                {session.patient?.age && (
                  <MetaBadge label="Age" value={String(session.patient.age)} />
                )}
                {session.patient?.gender && (
                  <MetaBadge label="Gender" value={session.patient.gender} />
                )}
                {session.patient?.phone && (
                  <MetaBadge label="Phone" value={session.patient.phone} />
                )}
                {session.category && (
                  <span className="px-2 py-0.5 bg-brand-light text-brand text-xs font-semibold rounded-full">
                    {session.category.label}
                    {session.category.source === "manual" && " (manual)"}
                  </span>
                )}
              </div>
            </div>
            <StatusBadge status={session.status} />
          </div>
          <div className="grid grid-cols-2 gap-4 text-xs text-gray-500 pt-2 border-t border-gray-100">
            <div><span className="font-medium text-gray-700">Phase:</span> {session.phase}</div>
            <div><span className="font-medium text-gray-700">Turns:</span> {session.turn_count}</div>
            <div><span className="font-medium text-gray-700">Language:</span> {session.language}</div>
            <div><span className="font-medium text-gray-700">Started:</span> {session.started_at_ist || "—"}</div>
            {session.ended_at_ist && (
              <div><span className="font-medium text-gray-700">Ended:</span> {session.ended_at_ist}</div>
            )}
          </div>
        </div>

        {/* Critical flags */}
        {critical.length > 0 && (
          <div className="space-y-2">
            <div className="bg-red-600 text-white text-sm font-bold px-4 py-2 rounded-xl">
              🚨 Critical Alerts
            </div>
            {critical.map((f, i) => (
              <div key={i} className="flag-critical">{f.description}</div>
            ))}
          </div>
        )}

        {/* Red flags */}
        {redFlags.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-bold text-gray-700">⚠️ Red Flags</h3>
            {redFlags.map((f, i) => (
              <div key={i} className="flag-red">{f.description}</div>
            ))}
          </div>
        )}

        {/* Other flags */}
        {others.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-bold text-gray-700">📌 Notes</h3>
            {others.map((f, i) => (
              <div key={i} className={f.flag_type === "IMPORTANT" ? "flag-important" : "flag-note"}>
                {f.description}
              </div>
            ))}
          </div>
        )}

        {/* Summary */}
        {session.summary && (
          <div className="card space-y-4">
            <h3 className="text-base font-bold text-gray-900">Clinical Summary</h3>
            <SummaryView summary={session.summary} />
          </div>
        )}

        {/* Q&A Transcript */}
        {session.qa_log.length > 0 && (
          <div className="card space-y-3">
            <h3 className="text-base font-bold text-gray-900">Full Transcript</h3>
            <div className="space-y-4">
              {session.qa_log
                .filter((e) => e.answer)
                .map((entry, i) => (
                  <div key={i} className="space-y-1">
                    <p className="text-xs font-semibold text-brand">Agent</p>
                    <p className="text-sm text-gray-700 bg-brand-light rounded-xl px-4 py-2.5">
                      {entry.question_text}
                    </p>
                    <p className="text-xs font-semibold text-gray-500 mt-2">Patient</p>
                    <p className="text-sm text-gray-800 bg-gray-50 rounded-xl px-4 py-2.5 border border-gray-100">
                      {entry.answer}
                    </p>
                  </div>
                ))}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

function MetaBadge({ label, value }: { label: string; value: string }) {
  return (
    <span className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full">
      {label}: {value}
    </span>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    completed: "bg-green-100 text-green-700",
    active: "bg-blue-100 text-blue-700",
    partial: "bg-amber-100 text-amber-700",
  };
  return (
    <span className={clsx("text-xs font-semibold px-2.5 py-1 rounded-full", colors[status] || "bg-gray-100 text-gray-600")}>
      {status}
    </span>
  );
}

function SummaryView({ summary }: { summary: Record<string, unknown> }) {
  const s = (summary.subjective || {}) as Record<string, string | null>;
  const fields = [
    ["Chief Complaint", s.chief_complaint],
    ["History", s.history_of_presenting_illness],
    ["Past Medical History", s.past_medical_history],
    ["Medications", s.medications],
    ["Allergies", s.allergies],
    ["Assessment", summary.assessment as string],
    ["Plan", summary.plan as string],
  ];
  return (
    <div className="space-y-3">
      {fields.map(([label, value]) =>
        value ? (
          <div key={label as string}>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-0.5">
              {label}
            </p>
            <p className="text-sm text-gray-800 leading-relaxed">{value}</p>
          </div>
        ) : null
      )}
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
