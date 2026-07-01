"use client";
import { useRouter, useParams } from "next/navigation";
import { useState, useEffect } from "react";
import {
  ArrowLeft,
  Stethoscope,
  ChevronDown,
  ChevronUp,
  Plus,
  Calendar,
  User,
  Phone,
  AlertTriangle,
  CheckCircle,
} from "lucide-react";
import { api, getToken } from "@/lib/api";
import type { Patient, ConsultationSummary, DiagnosisResult } from "@/lib/types";

const SPECIALTY_LABELS: Record<string, string> = {
  general_medicine: "General Medicine",
  psychotherapy: "Mental Health",
  gynecology: "Women's Health",
};

const STAGE_LABELS: Record<string, { label: string; color: string }> = {
  questionnaire: { label: "In Progress", color: "text-yellow-400" },
  completeness_check: { label: "Checking", color: "text-blue-400" },
  summary: { label: "Summarised", color: "text-indigo-400" },
  diagnosis: { label: "Diagnosed", color: "text-violet-400" },
  prescription: { label: "Prescribed", color: "text-teal-400" },
  finalized: { label: "Finalized", color: "text-emerald-400" },
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
  });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function DiagnosisSummary({ diagnosis }: { diagnosis: DiagnosisResult }) {
  return (
    <div className="space-y-2 mt-3">
      {diagnosis.urgent_concerns.length > 0 && (
        <div className="flex items-start gap-2 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <AlertTriangle className="w-3.5 h-3.5 text-red-400 mt-0.5 flex-shrink-0" />
          <p className="text-red-300 text-xs">{diagnosis.urgent_concerns.join(", ")}</p>
        </div>
      )}
      {diagnosis.differential_diagnoses.slice(0, 3).map((d, i) => (
        <div key={i} className="flex items-center gap-2">
          <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
            d.likelihood === "High" ? "bg-red-500/20 text-red-300" :
            d.likelihood === "Medium" ? "bg-yellow-500/20 text-yellow-300" :
            "bg-slate-500/20 text-slate-400"
          }`}>{d.likelihood}</span>
          <span className="text-slate-200 text-xs">{d.condition}</span>
          {d.icd_code && <span className="text-slate-500 text-xs">({d.icd_code})</span>}
        </div>
      ))}
      {diagnosis.suggested_workup.length > 0 && (
        <p className="text-slate-400 text-xs">
          Workup: {diagnosis.suggested_workup.slice(0, 2).join(", ")}
          {diagnosis.suggested_workup.length > 2 && ` +${diagnosis.suggested_workup.length - 2} more`}
        </p>
      )}
    </div>
  );
}

function SessionCard({ session }: { session: ConsultationSummary }) {
  const [expanded, setExpanded] = useState(false);
  const stage = STAGE_LABELS[session.current_stage] ?? { label: session.current_stage, color: "text-slate-400" };

  return (
    <div className="border border-white/10 rounded-xl overflow-hidden">
      {/* Summary row */}
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-4 py-3.5 text-left hover:bg-white/5 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-white text-sm font-semibold">
              {SPECIALTY_LABELS[session.specialty] ?? session.specialty}
            </span>
            <span className={`text-xs font-medium ${stage.color}`}>· {stage.label}</span>
          </div>
          <div className="flex items-center gap-1.5 mt-0.5">
            <Calendar className="w-3 h-3 text-slate-600" />
            <span className="text-slate-400 text-xs">{formatDateTime(session.created_at)}</span>
            {session.chief_complaint && (
              <span className="text-slate-500 text-xs truncate">· {session.chief_complaint}</span>
            )}
          </div>
        </div>
        {expanded ? (
          <ChevronUp className="w-4 h-4 text-slate-500 flex-shrink-0" />
        ) : (
          <ChevronDown className="w-4 h-4 text-slate-500 flex-shrink-0" />
        )}
      </button>

      {/* Expanded detail */}
      {expanded && (
        <div className="border-t border-white/10 px-4 py-4 space-y-4 bg-white/[0.02]">
          {session.diagnosis ? (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Diagnosis</p>
              <DiagnosisSummary diagnosis={session.diagnosis} />
            </div>
          ) : (
            <p className="text-slate-500 text-xs">No diagnosis recorded yet.</p>
          )}

          {session.prescription && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Prescription</p>
              {session.prescription.pharmacological.length > 0 ? (
                <div className="space-y-1.5">
                  {session.prescription.pharmacological.map((m, i) => (
                    <div key={i} className="flex items-center gap-2">
                      <CheckCircle className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                      <span className="text-slate-200 text-xs">
                        <span className="font-medium">{m.drug_name}</span>
                        {" "}{m.dose} · {m.frequency} · {m.duration}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-slate-500 text-xs">No pharmacological treatment.</p>
              )}
              {session.prescription.non_pharmacological.length > 0 && (
                <div className="mt-2 space-y-1">
                  {session.prescription.non_pharmacological.map((item, i) => (
                    <p key={i} className="text-slate-400 text-xs">• {item}</p>
                  ))}
                </div>
              )}
            </div>
          )}

          {session.summary && (
            <div>
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-widest mb-2">Clinical Summary</p>
              <pre className="text-slate-300 text-xs whitespace-pre-wrap leading-relaxed">
                {typeof session.summary === "string"
                  ? session.summary
                  : JSON.stringify(session.summary, null, 2)}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default function PatientDetailPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const patientId = params.id;

  const [patient, setPatient] = useState<Patient | null>(null);
  const [sessions, setSessions] = useState<ConsultationSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    getToken()
      .then(() =>
        api.getPatientHistory(patientId).then((data) => {
          setPatient(data.patient);
          setSessions(data.sessions);
        })
      )
      .catch((err) => {
        if (err.message === "refresh_failed") router.replace("/login");
        else setError("Failed to load patient.");
      })
      .finally(() => setLoading(false));
  }, [patientId, router]);

  if (loading) return null;
  if (error || !patient) {
    return (
      <main className="min-h-screen bg-[#0a0f1e] flex items-center justify-center">
        <div className="text-center">
          <p className="text-slate-400 text-sm mb-3">{error || "Patient not found."}</p>
          <button onClick={() => router.push("/patients")} className="text-indigo-400 text-sm underline">
            Back to patients
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#0a0f1e]">
      {/* Header */}
      <div className="sticky top-0 z-30 bg-[#0a0f1e]/90 backdrop-blur border-b border-white/5 px-4 py-3 flex items-center gap-3">
        <button
          onClick={() => router.push("/patients")}
          className="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="text-white font-semibold text-sm">Patient Profile</span>
      </div>

      <div className="max-w-2xl mx-auto px-4 py-8 space-y-6">
        {/* Patient info card */}
        <div className="bg-white/5 border border-white/10 rounded-2xl p-6">
          <div className="flex items-center gap-4 mb-5">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center text-white text-xl font-bold flex-shrink-0">
              {patient.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <h1 className="text-white text-xl font-bold">{patient.name}</h1>
              <p className="text-slate-400 text-sm mt-0.5">
                {patient.age} years{patient.gender ? ` · ${patient.gender}` : ""}
              </p>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="flex items-center gap-2">
              <Calendar className="w-3.5 h-3.5 text-slate-500" />
              <span className="text-slate-400 text-xs">Registered {formatDate(patient.created_at)}</span>
            </div>
            {patient.phone && (
              <div className="flex items-center gap-2">
                <Phone className="w-3.5 h-3.5 text-slate-500" />
                <span className="text-slate-400 text-xs">{patient.phone}</span>
              </div>
            )}
            <div className="flex items-center gap-2">
              <Stethoscope className="w-3.5 h-3.5 text-slate-500" />
              <span className="text-slate-400 text-xs">
                {sessions.length} consultation{sessions.length !== 1 ? "s" : ""}
              </span>
            </div>
          </div>
        </div>

        {/* New consultation CTA */}
        <button
          onClick={() => router.push(`/patients/${patientId}/consult`)}
          className="w-full flex items-center justify-center gap-2 bg-indigo-600 hover:bg-indigo-500 text-white font-semibold py-3.5 rounded-xl transition-colors"
        >
          <Plus className="w-5 h-5" />
          New Consultation
        </button>

        {/* Consultation history */}
        <div>
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-3">
            Consultation History
          </h2>
          {sessions.length === 0 ? (
            <div className="text-center py-10 border border-dashed border-white/10 rounded-xl">
              <User className="w-7 h-7 text-slate-600 mx-auto mb-2" />
              <p className="text-slate-500 text-sm">No consultations yet.</p>
              <p className="text-slate-600 text-xs mt-0.5">Start the first one above.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {sessions.map((s) => (
                <SessionCard key={s.session_id} session={s} />
              ))}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
