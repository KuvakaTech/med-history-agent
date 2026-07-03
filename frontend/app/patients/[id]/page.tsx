"use client";
import { useRouter, useParams } from "next/navigation";
import { useState, useEffect } from "react";
import {
  ArrowLeft, Stethoscope, ChevronDown, ChevronUp,
  Plus, Calendar, Phone, AlertTriangle, CheckCircle,
} from "lucide-react";
import { api, getToken } from "@/lib/api";
import type { Patient, ConsultationSummary, DiagnosisResult } from "@/lib/types";

const SPECIALTY_LABELS: Record<string, string> = {
  general_medicine: "General Medicine",
  psychotherapy:    "Mental Health",
  gynecology:       "Women's Health",
};

const STAGE_META: Record<string, { label: string; cls: string }> = {
  questionnaire:      { label: "In Progress",  cls: "bg-amber-50 text-amber-700 border-amber-200" },
  completeness_check: { label: "Checking",     cls: "bg-blue-50 text-blue-600 border-blue-200" },
  summary:            { label: "Summarised",   cls: "bg-indigo-50 text-indigo-600 border-indigo-200" },
  diagnosis:          { label: "Diagnosed",    cls: "bg-violet-50 text-violet-600 border-violet-200" },
  prescription:       { label: "Prescribed",   cls: "bg-teal-50 text-teal-600 border-teal-200" },
  finalized:          { label: "Finalized",    cls: "bg-emerald-50 text-emerald-700 border-emerald-200" },
};

const LIKELIHOOD_CLS: Record<string, string> = {
  High:   "bg-red-100 text-red-700",
  Medium: "bg-amber-100 text-amber-700",
  Low:    "bg-gray-100 text-gray-600",
};

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
}

function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", {
    day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function initials(name: string): string {
  return name.trim().split(/\s+/).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
}

function DiagnosisSummary({ diagnosis }: { diagnosis: DiagnosisResult }) {
  return (
    <div className="space-y-3">
      {/* Each urgent concern gets its own row */}
      {diagnosis.urgent_concerns.length > 0 && (
        <div className="space-y-2">
          {diagnosis.urgent_concerns.map((concern, i) => (
            <div key={i} className="flex items-start gap-2.5 bg-red-50 border border-red-100 rounded-lg px-3 py-2.5">
              <AlertTriangle className="w-3.5 h-3.5 text-red-500 mt-0.5 flex-shrink-0" />
              <p className="text-red-700 text-xs leading-relaxed">{concern}</p>
            </div>
          ))}
        </div>
      )}

      {/* Differential diagnoses */}
      {diagnosis.differential_diagnoses.slice(0, 3).map((d, i) => (
        <div key={i} className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-semibold px-1.5 py-0.5 rounded ${LIKELIHOOD_CLS[d.likelihood] ?? "bg-gray-100 text-gray-600"}`}>
            {d.likelihood}
          </span>
          <span className="text-gray-800 text-xs font-medium">{d.condition}</span>
          {d.icd_code && <span className="text-gray-400 text-xs">({d.icd_code})</span>}
        </div>
      ))}

      {/* Workup */}
      {diagnosis.suggested_workup.length > 0 && (
        <p className="text-gray-400 text-xs">
          Workup: {diagnosis.suggested_workup.slice(0, 2).join(", ")}
          {diagnosis.suggested_workup.length > 2 && ` +${diagnosis.suggested_workup.length - 2} more`}
        </p>
      )}
    </div>
  );
}

const SOAP_SECTION_LABELS: Record<string, string> = {
  subjective: "Subjective",
  objective:  "Objective",
  assessment: "Assessment",
  plan:       "Plan",
};

const SOAP_FIELD_LABELS: Record<string, string> = {
  chief_complaint:               "Chief complaint",
  history_of_presenting_illness: "HPI",
  past_medical_history:          "Past medical history",
  surgical_history:              "Surgical history",
  medications:                   "Medications",
  allergies:                     "Allergies",
  family_history:                "Family history",
  social_history:                "Social history",
  review_of_systems:             "Review of systems",
  vital_signs:                   "Vital signs",
  physical_examination:          "Physical exam",
};

const SOAP_LETTERS: Record<string, string> = {
  subjective: "S", objective: "O", assessment: "A", plan: "P",
};

function SoapNote({ summary }: { summary: unknown }) {
  if (!summary) return null;

  if (typeof summary === "string") {
    return <p className="text-gray-700 text-sm leading-relaxed">{summary}</p>;
  }

  const note = summary as Record<string, unknown>;
  const SECTION_ORDER = ["subjective", "objective", "assessment", "plan"];

  return (
    <div className="space-y-5">
      {SECTION_ORDER.map((section) => {
        const value = note[section];
        if (value === null || value === undefined) return null;

        const letter = SOAP_LETTERS[section];
        const label  = SOAP_SECTION_LABELS[section] ?? section;

        return (
          <div key={section}>
            <div className="flex items-center gap-2 mb-2.5">
              <span className="w-5 h-5 rounded-md bg-brand-light text-brand text-[10px] font-bold flex items-center justify-center flex-shrink-0">
                {letter}
              </span>
              <p className="text-xs font-bold text-gray-500 uppercase tracking-widest">{label}</p>
            </div>

            {typeof value === "string" ? (
              value.trim() ? (
                <p className="text-gray-700 text-xs leading-relaxed pl-7">{value}</p>
              ) : (
                <p className="text-gray-300 text-xs italic pl-7">Not recorded</p>
              )
            ) : typeof value === "object" && !Array.isArray(value) ? (
              <div className="pl-7 space-y-2">
                {Object.entries(value as Record<string, unknown>).map(([field, fieldValue]) => {
                  const isEmpty = fieldValue === null || fieldValue === undefined || fieldValue === "";
                  const display = isEmpty ? "Not recorded" : String(fieldValue);
                  return (
                    <div key={field} className="grid grid-cols-[140px_1fr] gap-3 items-start">
                      <span className="text-[11px] text-gray-400 font-medium pt-px leading-snug">
                        {SOAP_FIELD_LABELS[field] ?? field.replace(/_/g, " ")}
                      </span>
                      <span className={`text-xs leading-relaxed ${isEmpty ? "text-gray-300 italic" : "text-gray-700"}`}>
                        {display}
                      </span>
                    </div>
                  );
                })}
              </div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function SessionCard({ session }: { session: ConsultationSummary }) {
  const [expanded, setExpanded] = useState(false);
  const stage = STAGE_META[session.current_stage] ?? { label: session.current_stage, cls: "bg-gray-100 text-gray-600 border-gray-200" };

  return (
    <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full flex items-center gap-3 px-5 py-4 text-left hover:bg-gray-50 transition-colors"
      >
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-gray-900 text-sm font-semibold">
              {SPECIALTY_LABELS[session.specialty] ?? session.specialty}
            </span>
            <span className={`text-xs font-semibold px-2 py-0.5 rounded-full border ${stage.cls}`}>
              {stage.label}
            </span>
          </div>
          <div className="flex items-center gap-1.5 mt-1">
            <Calendar className="w-3 h-3 text-gray-300" />
            <span className="text-gray-400 text-xs">{formatDateTime(session.created_at)}</span>
            {session.chief_complaint && (
              <span className="text-gray-400 text-xs truncate">· {session.chief_complaint}</span>
            )}
          </div>
        </div>
        {expanded
          ? <ChevronUp className="w-4 h-4 text-gray-400 flex-shrink-0" />
          : <ChevronDown className="w-4 h-4 text-gray-400 flex-shrink-0" />
        }
      </button>

      {expanded && (
        <div className="border-t border-gray-100 px-5 py-5 space-y-5 bg-gray-50/60">
          {session.diagnosis ? (
            <div>
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">Diagnosis</p>
              <DiagnosisSummary diagnosis={session.diagnosis} />
            </div>
          ) : (
            <p className="text-gray-400 text-xs">No diagnosis recorded yet.</p>
          )}

          {session.prescription && (
            <div>
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">Prescription</p>
              {session.prescription.pharmacological.length > 0 ? (
                <div className="space-y-2">
                  {session.prescription.pharmacological.map((m, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <CheckCircle className="w-3.5 h-3.5 text-emerald-500 mt-0.5 flex-shrink-0" />
                      <span className="text-gray-700 text-xs">
                        <span className="font-semibold">{m.drug_name}</span>
                        {" "}{m.dose} · {m.frequency} · {m.duration}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-gray-400 text-xs">No pharmacological treatment.</p>
              )}
              {session.prescription.non_pharmacological.length > 0 && (
                <ul className="mt-3 space-y-1">
                  {session.prescription.non_pharmacological.map((item, i) => (
                    <li key={i} className="text-gray-500 text-xs flex items-start gap-1.5">
                      <span className="text-gray-300 mt-0.5">•</span>{item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {session.summary && (
            <div>
              <p className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-3">Clinical Summary</p>
              <SoapNote summary={session.summary} />
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
      <main className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center">
          <p className="text-gray-500 text-sm mb-3">{error || "Patient not found."}</p>
          <button onClick={() => router.push("/patients")} className="text-brand text-sm font-semibold hover:underline underline-offset-2">
            Back to patients
          </button>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-gray-50">
      {/* ── Header ── */}
      <header className="sticky top-0 z-30 bg-white border-b border-gray-100">
        <div className="max-w-3xl mx-auto px-6 flex items-center gap-3 h-14">
          <button
            onClick={() => router.push("/patients")}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Patients</span>
          </button>
          <span className="text-gray-200">/</span>
          <span className="text-sm text-gray-900 font-semibold truncate">{patient.name}</span>

          <div className="ml-auto">
            <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto" />
          </div>
        </div>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {/* ── Patient profile card ── */}
        <div className="bg-white border border-gray-100 rounded-xl p-6">
          <div className="flex items-start gap-5">
            {/* Avatar */}
            <div className="w-16 h-16 rounded-xl bg-brand-light text-brand flex items-center justify-center text-xl font-bold flex-shrink-0">
              {initials(patient.name)}
            </div>

            {/* Info */}
            <div className="flex-1 min-w-0">
              <h1 className="text-xl font-bold text-gray-900 leading-tight">{patient.name}</h1>
              <p className="text-gray-500 text-sm mt-0.5">
                {patient.age} years{patient.gender ? ` · ${patient.gender}` : ""}
              </p>

              <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-4">
                <div className="flex items-center gap-1.5 text-xs text-gray-400">
                  <Calendar className="w-3.5 h-3.5" />
                  Registered {formatDate(patient.created_at)}
                </div>
                {patient.phone && (
                  <div className="flex items-center gap-1.5 text-xs text-gray-400">
                    <Phone className="w-3.5 h-3.5" />
                    {patient.phone}
                  </div>
                )}
                <div className="flex items-center gap-1.5 text-xs text-gray-400">
                  <Stethoscope className="w-3.5 h-3.5" />
                  {sessions.length} consultation{sessions.length !== 1 ? "s" : ""}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* ── New consultation CTA ── */}
        <button
          onClick={() => router.push(`/patients/${patientId}/consult`)}
          className="btn-primary w-full flex items-center justify-center gap-2 py-3.5 text-sm"
        >
          <Plus className="w-4 h-4" />
          New Consultation
        </button>

        {/* ── Consultation history ── */}
        <div>
          <div className="flex items-center gap-2 mb-4">
            <h2 className="text-sm font-bold text-gray-900">Consultation History</h2>
            {sessions.length > 0 && (
              <span className="text-sm font-semibold text-gray-400">{sessions.length}</span>
            )}
          </div>

          {sessions.length === 0 ? (
            <div className="text-center py-12 border-2 border-dashed border-gray-200 rounded-xl">
              <div className="w-12 h-12 rounded-lg bg-brand-light flex items-center justify-center mx-auto mb-3">
                <Stethoscope className="w-5 h-5 text-brand" />
              </div>
              <p className="text-gray-700 font-semibold text-sm mb-1">No consultations yet</p>
              <p className="text-gray-400 text-xs">Start the first one using the button above.</p>
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
