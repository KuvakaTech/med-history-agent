"use client";
import { useRouter, useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { ArrowLeft, Stethoscope, Brain, Heart, ArrowRight } from "lucide-react";
import clsx from "clsx";
import { api, getToken } from "@/lib/api";
import type { Patient, Specialty } from "@/lib/types";

const SPECIALTIES: {
  label: string;
  value: Specialty;
  icon: React.ReactNode;
  desc: string;
  color: string;
}[] = [
  {
    label: "General Medicine",
    value: "general_medicine",
    icon: <Stethoscope className="w-5 h-5" />,
    desc: "Primary care & internal medicine",
    color: "from-blue-500 to-cyan-500",
  },
  {
    label: "Mental Health",
    value: "psychotherapy",
    icon: <Brain className="w-5 h-5" />,
    desc: "Psychotherapy & psychiatric assessment",
    color: "from-violet-500 to-purple-500",
  },
  {
    label: "Women's Health",
    value: "gynecology",
    icon: <Heart className="w-5 h-5" />,
    desc: "Gynaecology & obstetrics",
    color: "from-pink-500 to-rose-500",
  },
];

export default function NewConsultPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const patientId = params.id;

  const [patient, setPatient] = useState<Patient | null>(null);
  const [specialty, setSpecialty] = useState<Specialty>("general_medicine");
  const [language, setLanguage] = useState("");
  const [chiefComplaint, setChiefComplaint] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getToken()
      .then(() => api.getPatient(patientId).then(setPatient))
      .catch((err) => {
        if (err?.message === "refresh_failed") router.replace("/login");
      });
  }, [patientId, router]);

  const handleStart = async () => {
    setError("");
    setLoading(true);
    try {
      const data = await api.startConsultation(
        specialty,
        language.trim() || undefined,
        undefined,
        undefined,
        undefined,
        chiefComplaint.trim() || undefined,
        patientId,
      );
      router.push(`/consultation/${data.session_id}?q=${encodeURIComponent(data.opening_question)}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start consultation.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-[#0a0f1e]">
      {/* Header */}
      <div className="sticky top-0 z-30 bg-[#0a0f1e]/90 backdrop-blur border-b border-white/5 px-4 py-3 flex items-center gap-3">
        <button
          onClick={() => router.push(`/patients/${patientId}`)}
          className="p-1.5 rounded-lg hover:bg-white/10 text-slate-400 hover:text-white transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <span className="text-white font-semibold text-sm">New Consultation</span>
      </div>

      <div className="max-w-md mx-auto px-4 py-8 space-y-5">
        {/* Patient badge */}
        {patient && (
          <div className="flex items-center gap-3 bg-white/5 border border-white/10 rounded-xl px-4 py-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center text-white font-bold text-sm flex-shrink-0">
              {patient.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-white text-sm font-semibold">{patient.name}</p>
              <p className="text-slate-400 text-xs">
                {patient.age} yrs{patient.gender ? ` · ${patient.gender}` : ""}
              </p>
            </div>
          </div>
        )}

        {/* Specialty */}
        <div className="card">
          <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4">
            Type of consultation
          </h2>
          <div className="space-y-2.5">
            {SPECIALTIES.map((s) => (
              <button
                key={s.value}
                onClick={() => setSpecialty(s.value)}
                className={clsx(
                  "w-full flex items-center gap-4 p-4 rounded-xl border-2 text-left transition-all duration-200",
                  specialty === s.value
                    ? "border-indigo-300 bg-indigo-50 shadow-md shadow-indigo-100"
                    : "border-slate-100 hover:border-slate-200 hover:bg-slate-50/80 bg-white"
                )}
              >
                <span
                  className={clsx(
                    "w-9 h-9 rounded-xl flex items-center justify-center text-white bg-gradient-to-br shadow-sm flex-shrink-0",
                    s.color
                  )}
                >
                  {s.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div className={clsx("font-semibold text-sm", specialty === s.value ? "text-indigo-700" : "text-gray-800")}>
                    {s.label}
                  </div>
                  <div className="text-xs text-slate-500 mt-0.5">{s.desc}</div>
                </div>
                <div
                  className={clsx(
                    "w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all",
                    specialty === s.value ? "border-indigo-600 bg-indigo-600" : "border-slate-300"
                  )}
                >
                  {specialty === s.value && (
                    <svg className="w-2.5 h-2.5 text-white" fill="currentColor" viewBox="0 0 20 20">
                      <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                    </svg>
                  )}
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* Chief complaint (optional) */}
        <div className="card">
          <label className="text-xs font-bold text-slate-500 uppercase tracking-widest block mb-3">
            Chief complaint <span className="text-slate-400 font-normal normal-case">(optional)</span>
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="e.g. chest pain for 2 days, fever since yesterday…"
            value={chiefComplaint}
            onChange={(e) => setChiefComplaint(e.target.value)}
          />
        </div>

        {/* Language */}
        <div className="card">
          <label className="text-xs font-bold text-slate-500 uppercase tracking-widest block mb-3">
            Language preference
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="e.g. Hindi, Arabic, French — leave blank for English"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          />
          <p className="text-xs text-slate-400 mt-2">The AI will speak and understand your preferred language</p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm">
            {error}
          </div>
        )}

        <button
          className="btn-primary w-full text-base py-4 flex items-center justify-center gap-2"
          onClick={handleStart}
          disabled={loading || !patient}
        >
          {loading ? (
            <>
              <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Starting consultation…
            </>
          ) : (
            <>
              Begin Consultation
              <ArrowRight className="w-5 h-5" />
            </>
          )}
        </button>
      </div>
    </main>
  );
}
