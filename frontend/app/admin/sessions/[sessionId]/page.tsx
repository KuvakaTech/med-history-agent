"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { adminApi } from "@/lib/ticketing-api";
import type { Hospital, TicketFlag } from "@/lib/ticketing-types";
import { getToken } from "@/lib/api";
import clsx from "clsx";

interface DetailSession {
  session_id: string;
  ticket_number: string | null;
  opd_number?: number | null;
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
  address?: string | null;
  guardian_name?: string | null;
  flags: TicketFlag[];
  qa_log: Array<{ question_id: string; question_text: string; answer: string }>;
  summary: Record<string, unknown> | null;
  patient: {
    patient_id: string;
    name: string | null;
    age: number | null;
    gender: string | null;
    caste?: string | null;
    address?: string | null;
    guardian_name?: string | null;
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
  const [userRole, setUserRole] = useState("");
  const [hospitals, setHospitals] = useState<Hospital[]>([]);

  useEffect(() => {
    getToken()
      .then(async (t) => {
        // Decode token to get user role
        const payload = JSON.parse(atob(t.split('.')[1]));
        const role = payload.role;
        setUserRole(role);

        // Backend resolves scoping itself: hospital_admin is always scoped via
        // their JWT, super_admin passing no hospital_id gets a global lookup.
        const [sessionData] = await Promise.all([
          adminApi.getSession(t, sessionId, null),
          role === "super_admin"
            ? adminApi.listHospitals(t).then((r) => setHospitals(r.hospitals))
            : Promise.resolve(),
        ]);
        setSession(sessionData as unknown as DetailSession);
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
  }, [sessionId]);

  const sessionHospital = hospitals.find((h) => h.hospital_id === session?.hospital_id);

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
      <header className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <button
            onClick={() => router.push("/admin")}
            className="text-sm text-gray-500 hover:text-brand transition-colors"
          >
            ← Sessions
          </button>
          <span className="text-gray-300">|</span>
          <span className="text-sm font-mono text-gray-400">{sessionId.slice(0, 12)}…</span>
          {userRole === "super_admin" && (
            <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs font-semibold rounded-full">
              Super Admin
            </span>
          )}
        </div>

        {userRole === "super_admin" && sessionHospital && (
          <span className="text-xs font-semibold text-gray-500">
            {sessionHospital.name}
          </span>
        )}
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
              <div>
                {session.opd_number != null && (
                  <>
                    <p className="text-xs text-gray-400 uppercase tracking-wide">OPD Number</p>
                    <p className="text-3xl font-black font-mono text-brand tracking-tight">
                      {session.opd_number}
                    </p>
                  </>
                )}
                <p className="text-[11px] text-gray-400 font-mono mt-1">
                  Ticket {session.ticket_number}
                </p>
              </div>
              {session.started_at_ist && (
                <p className="text-xs text-gray-500">
                  {session.started_at_ist.slice(0, 10)}
                </p>
              )}
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
                {session.patient?.caste && (
                  <MetaBadge
                    label="Caste"
                    value={
                      session.patient.caste === "obc"
                        ? "OBC"
                        : session.patient.caste === "sc"
                        ? "SC"
                        : session.patient.caste === "st"
                        ? "ST"
                        : "General"
                    }
                  />
                )}
                {session.patient?.phone && (
                  <MetaBadge label="Phone" value={session.patient.phone} />
                )}
                <MetaBadge
                  label="Address"
                  value={session.address || session.patient?.address || ""}
                />
                <MetaBadge
                  label="Guardian"
                  value={session.guardian_name || session.patient?.guardian_name || ""}
                />
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
  
  const hasTranscript = Boolean(
    summary.full_transcript && typeof summary.full_transcript === "string" && summary.full_transcript.trim()
  );
  
  return (
    <div className="space-y-4">
      {/* SOAP Fields */}
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
      
      {/* Full Transcript from Summary */}
      {hasTranscript && (
        <div className="border-t pt-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">
            Complete Conversation Transcript
          </p>
          <div className="bg-gray-50 rounded-lg p-4 max-h-64 overflow-y-auto">
            <pre className="text-xs text-gray-700 leading-relaxed whitespace-pre-wrap font-sans">
              {summary.full_transcript as string}
            </pre>
          </div>
          <p className="text-xs text-gray-400 mt-1 italic">
            Generated conversation record between AI assistant and patient
          </p>
        </div>
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
