"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
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
  if (!data) return <p className="text-gray-400 italic">No clinical note generated.</p>;

  const renderValue = (v: unknown, depth = 0): React.ReactNode => {
    if (v === null || v === undefined || v === "") return null;
    if (typeof v === "string") return <span className="text-gray-700">{v}</span>;
    if (typeof v === "object" && !Array.isArray(v)) {
      return (
        <div className={clsx("space-y-2", depth > 0 && "pl-4 border-l-2 border-gray-100 mt-1")}>
          {Object.entries(v as Record<string, unknown>).map(([k, val]) => {
            if (!val) return null;
            return (
              <div key={k}>
                <span className="text-xs font-bold text-gray-500 uppercase tracking-wide">
                  {k.replace(/_/g, " ")}
                </span>
                <div className="mt-0.5">{renderValue(val, depth + 1)}</div>
              </div>
            );
          })}
        </div>
      );
    }
    return <span className="text-gray-700">{String(v)}</span>;
  };

  return <div className="space-y-4">{renderValue(data)}</div>;
}

function DxSection({ dx }: { dx: DiagnosisResult | null }) {
  if (!dx) return <p className="text-gray-400 italic">No diagnosis generated.</p>;

  const colorMap: Record<string, string> = {
    High: "border-red-400 bg-red-50",
    Medium: "border-amber-400 bg-amber-50",
    Low: "border-green-400 bg-green-50",
  };
  const iconMap: Record<string, string> = { High: "🔴", Medium: "🟡", Low: "🟢" };

  return (
    <div className="space-y-5">
      {dx.differential_diagnoses.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-700 mb-3">Differential Diagnoses</h3>
          <div className="space-y-3">
            {dx.differential_diagnoses.map((d, i) => (
              <div key={i} className={clsx("border-l-4 rounded-xl p-4", colorMap[d.likelihood] ?? colorMap.Low)}>
                <div className="font-semibold">
                  {iconMap[d.likelihood]} {d.condition}
                  <span className="text-xs font-normal text-gray-500 ml-2">({d.likelihood})</span>
                </div>
                <p className="text-sm text-gray-600 mt-1">{d.reasoning}</p>
                {d.icd_code && <p className="text-xs text-gray-400 mt-1">ICD-10: {d.icd_code}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {dx.urgent_concerns.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-700 mb-2">🚨 Urgent Concerns</h3>
          <ul className="space-y-1">
            {dx.urgent_concerns.map((u, i) => <li key={i} className="text-sm text-red-700">• {u}</li>)}
          </ul>
        </div>
      )}

      {dx.suggested_workup.length > 0 && (
        <div>
          <h3 className="font-semibold text-gray-700 mb-2">🔬 Suggested Workup</h3>
          <ul className="space-y-1">
            {dx.suggested_workup.map((w, i) => <li key={i} className="text-sm text-gray-600">• {w}</li>)}
          </ul>
        </div>
      )}

      {dx.physician_note && (
        <div className="bg-slate-50 border border-slate-200 rounded-xl p-4 text-sm text-slate-700">
          📋 {dx.physician_note}
        </div>
      )}
    </div>
  );
}

function MedCard({ med }: { med: Medication }) {
  return (
    <div className="border border-gray-200 rounded-xl p-4 space-y-2">
      <h4 className="font-bold text-gray-800">💊 {med.drug_name}</h4>
      <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <span className="text-gray-500">Dose</span><span className="text-gray-800">{med.dose}</span>
        <span className="text-gray-500">Frequency</span><span className="text-gray-800">{med.frequency}</span>
        <span className="text-gray-500">Duration</span><span className="text-gray-800">{med.duration}</span>
        {med.instructions && (<><span className="text-gray-500">Instructions</span><span className="text-gray-800">{med.instructions}</span></>)}
      </div>
      {med.warnings && (
        <p className="text-xs text-amber-700 bg-amber-50 rounded-lg px-3 py-2">⚠️ {med.warnings}</p>
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
      <p className="text-sm text-gray-500 italic">
        Doctor enters the confirmed diagnosis to generate a treatment plan.
      </p>
      <div className="flex gap-3">
        <input
          type="text"
          className="input-field flex-1"
          placeholder="e.g. Acute bronchitis, Major Depressive Episode…"
          value={confirmedDx}
          onChange={(e) => setConfirmedDx(e.target.value)}
        />
        <button className="btn-primary px-5" onClick={handleGenerate} disabled={loading || !confirmedDx.trim()}>
          {loading ? "Generating…" : "Generate"}
        </button>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}

      {rx && (
        <div className="space-y-4">
          {rx.pharmacological.map((m, i) => <MedCard key={i} med={m} />)}
          {rx.non_pharmacological.length > 0 && (
            <div>
              <h4 className="font-semibold text-gray-700 mb-2">Non-pharmacological</h4>
              {rx.non_pharmacological.map((n, i) => <p key={i} className="text-sm text-gray-600">🏃 {n}</p>)}
            </div>
          )}
          {rx.follow_up && <p className="text-sm text-gray-700">📅 <strong>Follow-up:</strong> {rx.follow_up}</p>}
          {rx.referrals.map((r, i) => <p key={i} className="text-sm text-gray-600">👨‍⚕️ {r}</p>)}
          <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-xs text-amber-700">
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
    { id: "note", label: "📝 Clinical Note" },
    { id: "diagnosis", label: "🔍 Diagnosis" },
    { id: "prescription", label: "💊 Prescription" },
  ];

  return (
    <div className="space-y-6">
      <div className="shimmer-bg rounded-2xl p-6 text-center shadow-lg shadow-indigo-500/20">
        <div className="text-4xl mb-2">🩺</div>
        <h2 className="text-xl font-bold text-white">Clinical Results Ready</h2>
        <p className="text-indigo-200 text-sm mt-1">Review and share with the treating physician.</p>
      </div>

      {/* Tabs */}
      <div className="flex rounded-xl overflow-hidden border border-slate-200 shadow-sm">
        {tabs.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={clsx(
              "flex-1 py-3 text-sm font-semibold transition-all",
              tab === t.id
                ? "shimmer-bg text-white"
                : "bg-white text-gray-600 hover:bg-slate-50"
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="card min-h-[300px]">
        {tab === "note" && <NoteSection data={note} />}
        {tab === "diagnosis" && <DxSection dx={diagnosis} />}
        {tab === "prescription" && <RxSection sessionId={sessionId} />}
      </div>

      {/* Actions */}
      <div className="flex gap-3">
        <button className="btn-secondary flex-1" onClick={handleDownload}>
          ⬇️ Download Record
        </button>
        <button className="btn-secondary flex-1" onClick={() => router.push("/")}>
          🔄 New Consultation
        </button>
      </div>
    </div>
  );
}
