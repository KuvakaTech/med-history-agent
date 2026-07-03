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
  iconCls: string;
}[] = [
  {
    label: "General Medicine",
    value: "general_medicine",
    icon: <Stethoscope className="w-5 h-5" />,
    desc: "Primary care & internal medicine",
    iconCls: "bg-blue-100 text-blue-600",
  },
  {
    label: "Mental Health",
    value: "psychotherapy",
    icon: <Brain className="w-5 h-5" />,
    desc: "Psychotherapy & psychiatric assessment",
    iconCls: "bg-violet-100 text-violet-600",
  },
  {
    label: "Women's Health",
    value: "gynecology",
    icon: <Heart className="w-5 h-5" />,
    desc: "Gynaecology & obstetrics",
    iconCls: "bg-rose-100 text-rose-600",
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
        undefined, undefined, undefined,
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
    <main className="min-h-screen bg-gray-50">
      {/* ── Header ── */}
      <header className="sticky top-0 z-30 bg-white border-b border-gray-100">
        <div className="max-w-xl mx-auto px-6 flex items-center gap-3 h-14">
          <button
            onClick={() => router.push(`/patients/${patientId}`)}
            className="flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-900 transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Back</span>
          </button>
          <span className="text-gray-200">/</span>
          <span className="text-sm text-gray-900 font-semibold">New Consultation</span>

          <div className="ml-auto">
            <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto" />
          </div>
        </div>
      </header>

      <div className="max-w-xl mx-auto px-6 py-8 space-y-5">
        {/* Patient badge */}
        {patient && (
          <div className="bg-white border border-gray-100 rounded-xl px-5 py-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-brand-light text-brand flex items-center justify-center font-bold text-sm flex-shrink-0">
              {patient.name.charAt(0).toUpperCase()}
            </div>
            <div>
              <p className="text-gray-900 text-sm font-semibold">{patient.name}</p>
              <p className="text-gray-400 text-xs mt-0.5">
                {patient.age} yrs{patient.gender ? ` · ${patient.gender}` : ""}
              </p>
            </div>
          </div>
        )}

        {/* Specialty */}
        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <h2 className="text-xs font-bold text-gray-400 uppercase tracking-widest mb-4">
            Type of consultation
          </h2>
          <div className="space-y-2.5">
            {SPECIALTIES.map((s) => (
              <button
                key={s.value}
                onClick={() => setSpecialty(s.value)}
                className={clsx(
                  "w-full flex items-center gap-4 p-4 rounded-lg border-2 text-left transition-all duration-150",
                  specialty === s.value
                    ? "border-brand bg-brand-light"
                    : "border-gray-100 bg-white hover:border-gray-200 hover:bg-gray-50"
                )}
              >
                <span className={clsx("w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0", s.iconCls)}>
                  {s.icon}
                </span>
                <div className="flex-1 min-w-0">
                  <div className={clsx("font-semibold text-sm", specialty === s.value ? "text-brand" : "text-gray-800")}>
                    {s.label}
                  </div>
                  <div className="text-xs text-gray-400 mt-0.5">{s.desc}</div>
                </div>
                <div className={clsx(
                  "w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all",
                  specialty === s.value ? "border-brand bg-brand" : "border-gray-300"
                )}>
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

        {/* Chief complaint */}
        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <label className="text-xs font-bold text-gray-400 uppercase tracking-widest block mb-3">
            Chief complaint <span className="text-gray-400 font-normal normal-case">(optional)</span>
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
        <div className="bg-white border border-gray-100 rounded-xl p-5">
          <label className="text-xs font-bold text-gray-400 uppercase tracking-widest block mb-3">
            Language preference
          </label>
          <input
            type="text"
            className="input-field"
            placeholder="e.g. Hindi, Arabic, French — leave blank for English"
            value={language}
            onChange={(e) => setLanguage(e.target.value)}
          />
          <p className="text-xs text-gray-400 mt-2">The AI will speak and understand your preferred language.</p>
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm font-medium">
            {error}
          </div>
        )}

        <button
          className="btn-primary w-full py-4 text-sm flex items-center justify-center gap-2"
          onClick={handleStart}
          disabled={loading || !patient}
        >
          {loading ? (
            <>
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Starting consultation…
            </>
          ) : (
            <>
              Begin Consultation
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </button>
      </div>
    </main>
  );
}
