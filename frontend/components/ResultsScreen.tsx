"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { Download, RefreshCw, AlertTriangle, CheckCircle, FlaskConical, ClipboardList } from "lucide-react";
import type { DiagnosisResult, Medication, PrescriptionResult } from "@/lib/types";
import { api } from "@/lib/api";
import clsx from "clsx";

interface Props {
  sessionId: string;
  note: Record<string, unknown> | null;
  diagnosis: DiagnosisResult | null;
}

type Tab = "note" | "diagnosis" | "prescription";

function NoteSection({ data }: { data: Record<string, unknown> | null }) {
  if (!data) return <p className="text-gray-400 italic text-sm">No clinical note generated.</p>;

  const renderValue = (v: unknown, depth = 0): React.ReactNode => {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "string") return <span className="text-gray-700 text-sm leading-relaxed">{v}</span>;
    if (typeof v === "object" && !Array.isArray(v)) {
      return (
        <div className={clsx("space-y-3", depth > 0 && "pl-4 border-l-2 border-gray-100 mt-1")}>
          {Object.entries(v as Record<string, unknown>).map(([k, val]) => {
            if (!val) return null;
            return (
              <div key={k}>
                <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-1">
                  {k.replace(/_/g, " ")}
                </p>
                {renderValue(val, depth + 1)}
              </div>
            );
          })}
        </div>
      );
    }
    return <span className="text-gray-700 text-sm">{String(v)}</span>;
  };

  return <div className="space-y-4">{renderValue(data)}</div>;
}

const LIKELIHOOD_STYLE: Record<string, { card: string; badge: string }> = {
  High:   { card: "border-l-red-400 bg-red-50",    badge: "bg-red-100 text-red-700" },
  Medium: { card: "border-l-amber-400 bg-amber-50", badge: "bg-amber-100 text-amber-700" },
  Low:    { card: "border-l-green-400 bg-green-50", badge: "bg-green-100 text-green-700" },
};

function DxSection({ dx }: { dx: DiagnosisResult | null }) {
  if (!dx) return <p className="text-gray-400 italic text-sm">No diagnosis generated.</p>;

  return (
    <div className="space-y-6">
      {dx.differential_diagnoses.length > 0 && (
        <div>
          <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">Differential Diagnoses</p>
          <div className="space-y-3">
            {dx.differential_diagnoses.map((d, i) => {
              const style = LIKELIHOOD_STYLE[d.likelihood] ?? LIKELIHOOD_STYLE.Low;
              return (
                <div key={i} className={clsx("border-l-4 rounded-lg p-4", style.card)}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className={clsx("text-xs font-bold px-2 py-0.5 rounded-full", style.badge)}>
                      {d.likelihood}
                    </span>
                    <span className="font-semibold text-gray-800 text-sm">{d.condition}</span>
                    {d.icd_code && <span className="text-xs text-gray-400 ml-auto">{d.icd_code}</span>}
                  </div>
                  <p className="text-sm text-gray-600 leading-relaxed">{d.reasoning}</p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {dx.urgent_concerns.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-4 h-4 text-red-500" />
            <p className="text-xs font-bold text-gray-400 uppercase tracking-widest">Urgent Concerns</p>
          </div>
          <ul className="space-y-1.5">
            {dx.urgent_concerns.map((u, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-red-700">
                <span className="text-red-400 mt-0.5">•</span>{u}
              </li>
            ))}
          </ul>
        </div>
      )}

      {dx.suggested_workup.length > 0 && (
        <div>
          <div className="flex items-center gap-2 mb-3">
            <FlaskConical className="w-4 h-4 text-gray-400" />
            <p className="text-xs font-bold text-gray-400 uppercase tracking-widest">Suggested Workup</p>
          </div>
          <ul className="space-y-1.5">
            {dx.suggested_workup.map((w, i) => (
              <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                <span className="text-gray-300 mt-0.5">•</span>{w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {dx.physician_note && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-4">
          <div className="flex items-start gap-2">
            <ClipboardList className="w-4 h-4 text-gray-400 mt-0.5 flex-shrink-0" />
            <p className="text-sm text-gray-700">{dx.physician_note}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function MedCard({ med }: { med: Medication }) {
  return (
    <div className="border border-gray-100 rounded-lg p-4 space-y-3">
      <div className="flex items-center gap-2">
        <div className="w-7 h-7 bg-brand-light rounded-lg flex items-center justify-center text-brand text-sm">💊</div>
        <h4 className="font-bold text-gray-800 text-sm">{med.drug_name}</h4>
      </div>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
        <span className="text-gray-400">Dose</span><span className="text-gray-800 font-medium">{med.dose}</span>
        <span className="text-gray-400">Frequency</span><span className="text-gray-800 font-medium">{med.frequency}</span>
        <span className="text-gray-400">Duration</span><span className="text-gray-800 font-medium">{med.duration}</span>
        {med.instructions && (
          <><span className="text-gray-400">Instructions</span><span className="text-gray-800 font-medium">{med.instructions}</span></>
        )}
      </div>
      {med.warnings && (
        <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg px-3 py-2">
          ⚠️ {med.warnings}
        </p>
      )}
    </div>
  );
}

function RxSection({ sessionId }: { sessionId: string }) {
  const [confirmedDx, setConfirmedDx] = useState("");
  const [rx, setRx] = useState<PrescriptionResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleGenerate = async () => {
    if (!confirmedDx.trim()) return;
    setLoading(true);
    setError("");
    try {
      const data = await api.prescribe(sessionId, confirmedDx.trim());
      setRx(data.prescription);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to generate prescription.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-sm text-gray-500">
        Enter the confirmed diagnosis to generate a personalised treatment plan.
      </p>
      <div className="flex gap-3">
        <input
          type="text"
          className="input-field flex-1"
          placeholder="e.g. Acute bronchitis, Major Depressive Episode…"
          value={confirmedDx}
          onChange={(e) => setConfirmedDx(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") handleGenerate(); }}
        />
        <button
          className="btn-primary px-5 text-sm"
          onClick={handleGenerate}
          disabled={loading || !confirmedDx.trim()}
        >
          {loading ? "Generating…" : "Generate"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600 font-medium">{error}</p>}

      {rx && (
        <div className="space-y-4">
          {rx.pharmacological.map((m, i) => <MedCard key={i} med={m} />)}
          {rx.non_pharmacological.length > 0 && (
            <div>
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-2">Non-pharmacological</p>
              <ul className="space-y-1.5">
                {rx.non_pharmacological.map((n, i) => (
                  <li key={i} className="flex items-start gap-2 text-sm text-gray-600">
                    <CheckCircle className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
                    {n}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {rx.follow_up && (
            <p className="text-sm text-gray-700">
              <span className="font-semibold">Follow-up:</span> {rx.follow_up}
            </p>
          )}
          {rx.referrals.map((r, i) => (
            <p key={i} className="text-sm text-gray-600">👨‍⚕️ {r}</p>
          ))}
          <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-xs text-amber-700 font-medium">
            ⚠️ Requires physician review and approval before dispensing.
          </div>
        </div>
      )}
    </div>
  );
}

export default function ResultsScreen({ sessionId, note, diagnosis }: Props) {
  const router = useRouter();
  const [tab, setTab] = useState<Tab>("note");

  const handleDownload = async () => {
    try {
      const data = await api.finalize(sessionId);
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `consultation_${sessionId.slice(0, 8)}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert("Download failed.");
    }
  };

  const tabs: { id: Tab; label: string }[] = [
    { id: "note",         label: "Clinical Note" },
    { id: "diagnosis",    label: "Diagnosis" },
    { id: "prescription", label: "Prescription" },
  ];

  return (
    <div className="space-y-5 fade-up">
      {/* Banner */}
      <div className="bg-brand rounded-xl p-6 text-center">
        <div className="w-12 h-12 bg-white/15 rounded-xl flex items-center justify-center mx-auto mb-3">
          <svg viewBox="0 0 24 24" className="w-6 h-6 text-white" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M22 12h-4l-3 9L9 3l-3 9H2" />
          </svg>
        </div>
        <h2 className="text-xl font-bold text-white">Clinical Results Ready</h2>
        <p className="text-white/70 text-sm mt-1">Review and share with the treating physician.</p>
      </div>

      {/* Tabs */}
      <div className="flex bg-gray-100 rounded-lg p-1 gap-1">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "flex-1 py-2.5 text-sm font-semibold rounded-lg transition-all duration-150",
              tab === t.id
                ? "bg-white text-brand shadow-sm"
                : "text-gray-500 hover:text-gray-700"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="bg-white border border-gray-100 rounded-xl p-6 min-h-[300px]">
        {tab === "note"         && <NoteSection data={note} />}
        {tab === "diagnosis"    && <DxSection dx={diagnosis} />}
        {tab === "prescription" && <RxSection sessionId={sessionId} />}
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button className="btn-secondary flex-1 flex items-center justify-center gap-2 text-sm" onClick={handleDownload}>
          <Download className="w-4 h-4" />
          Download Record
        </button>
        <button className="btn-secondary flex-1 flex items-center justify-center gap-2 text-sm" onClick={() => router.push("/")}>
          <RefreshCw className="w-4 h-4" />
          New Consultation
        </button>
      </div>
    </div>
  );
}
