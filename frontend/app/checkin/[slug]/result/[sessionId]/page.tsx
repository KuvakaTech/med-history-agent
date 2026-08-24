"use client";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ticketApi } from "@/lib/ticketing-api";
import type { SessionResultResponse, SOAPSummary, TicketFlag } from "@/lib/ticketing-types";
import clsx from "clsx";

export default function ResultPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;

  const [result, setResult] = useState<SessionResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [discarding, setDiscarding] = useState(false);
  const [discarded, setDiscarded] = useState(false);
  const printRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ticketApi
      .getResult(slug, sessionId)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug, sessionId]);

  const handleDiscard = async () => {
    if (!confirm("Discard this check-in record? This cannot be undone.")) return;
    setDiscarding(true);
    await ticketApi.discard(slug, sessionId).catch(() => {});
    setDiscarded(true);
    setDiscarding(false);
  };

  if (loading) return <LoadingState />;
  if (error) return <ErrorState message={error} />;
  if (!result) return null;
  if (discarded) return <DiscardedState slug={slug} />;

  const criticalFlags = result.flags.filter((f) => f.flag_type === "CRITICAL_RED_FLAG");
  const redFlags = result.flags.filter((f) => f.flag_type === "RED_FLAG");
  const otherFlags = result.flags.filter(
    (f) => f.flag_type !== "CRITICAL_RED_FLAG" && f.flag_type !== "RED_FLAG"
  );
  const p = result.patient;

  return (
    <main className="min-h-screen bg-gray-50">
      {/* ── Screen header (hidden on print) ── */}
      <header className="bg-white border-b border-gray-100 px-5 h-14 flex items-center justify-between sticky top-0 z-50 print:hidden">
        <div className="flex items-center gap-3">
          <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto" />
          <span className="text-xs text-gray-400">Check-In Summary</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => window.print()}
            className="btn-secondary text-xs py-2 px-3 flex items-center gap-1.5"
          >
            <span>🖨️</span> Print
          </button>
          <button
            onClick={handleDiscard}
            disabled={discarding}
            className="text-xs text-red-500 hover:text-red-700 px-3 py-2 rounded-lg hover:bg-red-50 transition-colors disabled:opacity-50"
          >
            {discarding ? "Discarding…" : "Discard"}
          </button>
        </div>
      </header>

      {/* ── Printable content ── */}
      <div ref={printRef} className="max-w-2xl mx-auto px-4 py-8 space-y-5 fade-up">

        {/* Partial warning */}
        {result.status === "partial" && (
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800 flex gap-2 items-start print:hidden">
            <span className="mt-0.5">⚠️</span>
            <span>This check-in was not completed. Partial record shown below.</span>
          </div>
        )}

        {/* ── Receipt / ticket header ── */}
        <div className="card print:border print:shadow-none">
          {/* Hospital + ticket number row */}
          <div className="flex items-start justify-between pb-4 border-b border-gray-100">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-semibold mb-0.5">
                {result.hospital_name || "Hospital"}
              </p>
              <p className="text-xs text-gray-500">Pre-Visit Check-In Receipt</p>
            </div>
            {result.ticket_number && (
              <div className="text-right">
                <p className="text-xs text-gray-400 uppercase tracking-wide mb-0.5">Ticket No.</p>
                <p className="text-2xl font-black text-brand tracking-tight font-mono">
                  {result.ticket_number}
                </p>
              </div>
            )}
          </div>

          {/* Patient details */}
          <div className="pt-4 grid grid-cols-2 gap-y-3 gap-x-6">
            <PatientField label="Name" value={p?.name || "Not provided"} />
            <PatientField label="Phone" value={p?.phone || "—"} />
            <PatientField
              label="Age"
              value={p?.age != null ? `${p.age} years` : "Not provided"}
            />
            <PatientField
              label="Gender"
              value={p?.gender ? capitalize(p.gender) : "Not provided"}
            />
            <PatientField label="Department" value={result.category?.label || "Not determined"} />
            <PatientField
              label="Category Source"
              value={result.category?.source === "manual" ? "Selected manually" : "Auto-detected"}
            />
            <PatientField label="Check-In Time" value={result.started_at || "—"} />
            {result.ended_at && (
              <PatientField label="Completed" value={result.ended_at} />
            )}
            <PatientField
              label="Status"
              value={capitalize(result.status)}
              valueClass={clsx(
                "font-semibold",
                result.status === "completed"
                  ? "text-green-700"
                  : result.status === "partial"
                  ? "text-amber-700"
                  : "text-blue-700"
              )}
            />
          </div>
        </div>

        {/* ── Critical flags — always first ── */}
        {criticalFlags.length > 0 && (
          <div className="space-y-2">
            <div className="bg-red-600 text-white text-sm font-bold px-4 py-2.5 rounded-xl flex items-center gap-2">
              <span>🚨</span> Critical Alerts — Immediate Physician Review Required
            </div>
            {criticalFlags.map((f, i) => (
              <div key={i} className="flag-critical">{f.description}</div>
            ))}
          </div>
        )}

        {/* ── Red flags ── */}
        {redFlags.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide">⚠️ Red Flags</h3>
            {redFlags.map((f, i) => (
              <div key={i} className="flag-red">{f.description}</div>
            ))}
          </div>
        )}

        {/* ── Other flags ── */}
        {otherFlags.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide">📌 Notes</h3>
            {otherFlags.map((f, i) => (
              <div key={i} className={f.flag_type === "IMPORTANT" ? "flag-important" : "flag-note"}>
                {f.description}
              </div>
            ))}
          </div>
        )}

        {/* ── SOAP Summary ── */}
        {result.summary && <SummaryCard summary={result.summary} />}

        {!result.summary && result.status === "completed" && (
          <div className="card text-sm text-gray-500 text-center py-8">
            Summary is being processed. Please refresh in a moment.
          </div>
        )}

        {/* ── Print footer ── */}
        <div className="hidden print:block border-t pt-4 space-y-1 text-xs text-gray-400 text-center">
          <p>Kuvaka Clinical AI · Pre-Visit Check-In</p>
          <p>
            {result.hospital_name && <span>{result.hospital_name} · </span>}
            {result.ticket_number && <span>{result.ticket_number} · </span>}
            {result.started_at}
          </p>
          <p className="text-gray-300">
            This is a pre-visit intake summary, not a medical diagnosis or prescription.
          </p>
        </div>
      </div>
    </main>
  );
}

// ── Sub-components ─────────────────────────────────────────────

function PatientField({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div>
      <p className="text-xs text-gray-400 uppercase tracking-wide mb-0.5">{label}</p>
      <p className={clsx("text-sm text-gray-800 font-medium", valueClass)}>{value}</p>
    </div>
  );
}

function SummaryCard({ summary }: { summary: SOAPSummary }) {
  const s = summary.subjective;
  const fields: [string, string | null | undefined][] = [
    ["Chief Complaint", s?.chief_complaint],
    ["History", s?.history_of_presenting_illness],
    ["Past Medical History", s?.past_medical_history],
    ["Surgical History", s?.surgical_history],
    ["Current Medications", s?.medications],
    ["Allergies", s?.allergies],
    ["Family History", s?.family_history],
    ["Assessment", summary.assessment],
    ["Plan / Next Steps", summary.plan],
  ];

  const visible = fields.filter(([, v]) => v?.trim());
  if (visible.length === 0) return null;

  return (
    <div className="card space-y-4 print:border print:shadow-none">
      <h3 className="text-base font-bold text-gray-900">Clinical Summary</h3>
      <div className="space-y-3">
        {visible.map(([label, value]) => (
          <div key={label}>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
              {label}
            </p>
            <p className="text-sm text-gray-800 leading-relaxed">{value}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

function capitalize(s: string) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function LoadingState() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <div className="text-center space-y-3">
        <svg className="animate-spin w-8 h-8 text-brand mx-auto" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
        <p className="text-sm text-gray-500">Loading your results…</p>
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="text-center space-y-3 max-w-sm">
        <div className="text-4xl">😕</div>
        <p className="text-gray-600 text-sm">{message}</p>
      </div>
    </div>
  );
}

function DiscardedState({ slug }: { slug: string }) {
  const router = useRouter();
  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 px-4">
      <div className="text-center space-y-4 max-w-sm">
        <div className="text-4xl">🗑️</div>
        <p className="text-gray-700 font-medium">Record discarded</p>
        <p className="text-gray-500 text-sm">Your check-in record has been removed.</p>
        <button onClick={() => router.push(`/checkin/${slug}/start`)} className="btn-primary">
          Start New Check-In
        </button>
      </div>
    </div>
  );
}
