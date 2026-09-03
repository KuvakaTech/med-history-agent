"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { ticketApi } from "@/lib/ticketing-api";
import type { SessionResultResponse, SOAPSummary, TicketFlag } from "@/lib/ticketing-types";
import clsx from "clsx";

export default function ResultPage() {
  return (
    <Suspense fallback={null}>
      <ResultPageInner />
    </Suspense>
  );
}

function ResultPageInner() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;
  const autoprint = searchParams.get("autoprint") === "1";

  const [result, setResult] = useState<SessionResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [discarding, setDiscarding] = useState(false);
  const [discarded, setDiscarded] = useState(false);
  const [countdown, setCountdown] = useState<number | null>(null);
  const printRef = useRef<HTMLDivElement>(null);
  const printTriggeredRef = useRef(false);
  const countdownStartedRef = useRef(false);

  useEffect(() => {
    ticketApi
      .getResult(slug, sessionId)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug, sessionId]);

  // Auto-print the receipt after a 5s countdown, only when landing here fresh
  // from a just-finished consultation (?autoprint=1). On kiosk machines
  // launched with Chrome/Edge's --kiosk-printing flag, window.print() sends
  // straight to the default printer with no dialog; without that flag the
  // browser still shows its normal print dialog.
  useEffect(() => {
    if (!result || !autoprint || countdownStartedRef.current) return;
    countdownStartedRef.current = true;
    setCountdown(5);
  }, [result, autoprint]);

  useEffect(() => {
    if (countdown === null) return;
    if (countdown === 0) {
      printTriggeredRef.current = true;
      setCountdown(null);
      window.print();
      return;
    }
    const t = setTimeout(() => setCountdown((c) => (c !== null ? c - 1 : c)), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  // After the auto-triggered print finishes (dialog closed, or sent silently
  // to the printer under --kiosk-printing), head back to start a fresh check-in.
  useEffect(() => {
    if (!autoprint) return;
    const handleAfterPrint = () => {
      if (printTriggeredRef.current) {
        router.replace(`/checkin/${slug}/start`);
      }
    };
    window.addEventListener("afterprint", handleAfterPrint);
    return () => window.removeEventListener("afterprint", handleAfterPrint);
  }, [autoprint, slug, router]);

  const handleCancelAutoPrint = () => {
    setCountdown(null);
  };

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
        {countdown !== null ? (
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-brand">Printing in {countdown}s</span>
            <button
              onClick={handleCancelAutoPrint}
              className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <button
              onClick={() => router.push(`/checkin/${slug}/`)}
              className="btn-secondary text-xs py-2 px-3 flex items-center gap-1.5"
            >
              ← Back to Check-In
            </button>
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
        )}
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
        <div className="card print:border-0 print:shadow-none print:p-0">
          {/* Hospital + ticket number row */}
          <div className="flex items-start justify-between pb-4 border-b border-gray-100 print:hidden">
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

          {/* Patient details — compact single-line fields */}
          <div className="flex flex-wrap gap-x-8 gap-y-2">
            {result.ticket_number && (
              <PatientField label="Ticket No." value={result.ticket_number} />
            )}
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

        {/* ── SOAP Summary ── */}
        {result.summary && <SummaryCard summary={result.summary} />}

        {!result.summary && result.status === "completed" && (
          <div className="card text-sm text-gray-500 text-center py-8">
            Summary is being processed. Please refresh in a moment.
          </div>
        )}

        {/* ── Notes (other flags) — shown last ── */}
        {otherFlags.length > 0 && (
          <div className="space-y-2">
            <h3 className="text-sm font-bold text-gray-700 uppercase tracking-wide">
              <span className="print:hidden">📌 </span>Notes
            </h3>
            {otherFlags.map((f, i) => (
              <div
                key={i}
                className={clsx(
                  f.flag_type === "IMPORTANT" ? "flag-important" : "flag-note",
                  "print:bg-transparent print:border-0 print:border-l-0 print:text-gray-800 print:p-0"
                )}
              >
                {f.description}
              </div>
            ))}
          </div>
        )}

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
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap">
      <span className="text-xs text-gray-400 uppercase tracking-wide">{label}:</span>
      <span className={clsx("text-sm text-gray-800 font-medium", valueClass)}>{value}</span>
    </span>
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
  const hasTranscript = summary.full_transcript?.trim();
  
  if (visible.length === 0 && !hasTranscript) return null;

  return (
    <div className="space-y-6">
      {/* Clinical Summary Section */}
      {visible.length > 0 && (
        <div className="card space-y-4 print:border-0 print:shadow-none print:p-0">
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
      )}
      
      {/* Full Transcript Section — screen only */}
      {hasTranscript && (
        <div className="card space-y-4 print:hidden">
          <h3 className="text-base font-bold text-gray-900">Full Conversation Transcript</h3>
          <div className="bg-gray-50 rounded-lg p-4 max-h-96 overflow-y-auto">
            <pre className="text-sm text-gray-700 leading-relaxed whitespace-pre-wrap font-sans">
              {summary.full_transcript}
            </pre>
          </div>
          <p className="text-xs text-gray-500 italic">
            Complete conversation record between AI assistant and patient
          </p>
        </div>
      )}
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
