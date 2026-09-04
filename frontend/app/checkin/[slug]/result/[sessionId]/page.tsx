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
  const [printScale, setPrintScale] = useState(1);
  const printRef = useRef<HTMLDivElement>(null);
  const printContentRef = useRef<HTMLDivElement>(null);
  const pageRulerRef = useRef<HTMLDivElement>(null);
  const printTriggeredRef = useRef(false);
  const countdownStartedRef = useRef(false);

  // Shrink the printed content (via CSS transform, since Tailwind's rem-based
  // text sizes ignore a parent font-size override) so it always occupies at
  // most half of one printed page — and clamp the page itself to exactly one
  // page tall so it can never spill onto a second page, no matter how much
  // clinical data there is. `pageRulerRef` is a hidden 100vh element whose
  // measured height (only meaningful once @media print is active) tells us
  // the true pixel height of one physical page.
  useEffect(() => {
    const fitToPage = () => {
      const content = printContentRef.current;
      const ruler = pageRulerRef.current;
      if (!content || !ruler) return;
      content.style.transform = "";
      content.style.width = "";
      const naturalHeight = content.scrollHeight;
      const onePagePx = ruler.getBoundingClientRect().height || window.innerHeight;
      const targetHeight = onePagePx * 0.5;
      const scale =
        naturalHeight > targetHeight
          ? Math.max(targetHeight / naturalHeight, 0.4)
          : 1;
      setPrintScale(scale);
    };
    const reset = () => {
      setPrintScale(1);
    };
    const mql = window.matchMedia("print");
    const handleChange = (e: MediaQueryListEvent) => (e.matches ? fitToPage() : reset());
    mql.addEventListener("change", handleChange);
    window.addEventListener("beforeprint", fitToPage);
    window.addEventListener("afterprint", reset);
    return () => {
      mql.removeEventListener("change", handleChange);
      window.removeEventListener("beforeprint", fitToPage);
      window.removeEventListener("afterprint", reset);
    };
  }, []);

  useEffect(() => {
    ticketApi
      .getResult(slug, sessionId)
      .then(setResult)
      .catch((e) => {
        if (e.message === "kiosk_locked") {
          router.replace(`/checkin/${slug}/start`);
          return;
        }
        setError(e.message);
      })
      .finally(() => setLoading(false));
  }, [slug, sessionId, router]);

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

        {/* Hidden ruler — its rendered height (only meaningful once @media
            print is active) tells us the true pixel height of one page. */}
        <div
          ref={pageRulerRef}
          className="hidden print:block"
          style={{ height: "100vh", position: "fixed", top: 0, left: 0, width: 1, visibility: "hidden", pointerEvents: "none" }}
          aria-hidden="true"
        />

        {/* Print-only: clamp to exactly one page so content can never spill
            onto a second page — the shrunk content (see printContentRef)
            occupies at most half of it, leaving the rest blank. */}
        <div className="print:h-screen print:overflow-hidden space-y-5">
        <div
          ref={printContentRef}
          className="space-y-5"
          style={
            printScale !== 1
              ? {
                  transform: `scale(${printScale})`,
                  transformOrigin: "top left",
                  width: `${100 / printScale}%`,
                }
              : undefined
          }
        >

        {/* ── Receipt / ticket header ── */}
        <div className="card print:border-0 print:shadow-none print:p-0">
          {/* Hospital + OPD header (print + screen) */}
          <div className="flex items-start justify-between pb-4 border-b border-gray-100">
            <div>
              <p className="text-xs text-gray-400 uppercase tracking-wide font-semibold mb-0.5">
                {result.hospital_name || "Hospital"}
              </p>
              <p className="text-xs text-gray-500">OPD Slip</p>
              {(result.opd_date_ist || result.started_at) && (
                <p className="text-sm text-gray-700 mt-1">
                  Date: {result.opd_date_ist || result.started_at?.slice(0, 10)}
                </p>
              )}
            </div>
            <div className="text-right">
              {result.opd_number != null && (
                <div>
                  <p className="text-xs text-gray-400 uppercase tracking-wide mb-0.5">OPD No.</p>
                  <p className="text-4xl font-black text-brand tracking-tight font-mono leading-none">
                    {result.opd_number}
                  </p>
                </div>
              )}
              {result.ticket_number && (
                <p className="text-[11px] text-gray-400 font-mono mt-2">
                  Ticket {result.ticket_number}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-8 gap-y-2 pt-4">
            <PatientField label="Patient's Name" value={p?.name ?? ""} />
            {result.collect_caste && (
              <PatientField
                label="Caste"
                value={
                  p?.caste === "obc"
                    ? "OBC"
                    : p?.caste === "sc"
                    ? "SC"
                    : p?.caste === "st"
                    ? "ST"
                    : p?.caste === "general"
                    ? "General"
                    : ""
                }
              />
            )}
            <PatientField label="Age" value={p?.age != null ? String(p.age) : ""} />
            <PatientField label="Sex" value={p?.gender ? capitalize(p.gender) : ""} />
            <PatientField label="Address" value={p?.address ?? ""} />
            <PatientField label="Guardian Name" value={p?.guardian_name ?? ""} />
            <PatientField label="Phone" value={p?.phone ?? ""} />
            <PatientField label="Department" value={result.category?.label ?? ""} />
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
    <span className="inline-flex items-baseline gap-1.5 min-w-0">
      <span className="text-xs text-gray-400 uppercase tracking-wide shrink-0">{label}:</span>
      <span className={clsx("text-sm text-gray-800 font-medium min-h-[1.25rem]", valueClass)}>
        {value}
      </span>
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
