"use client";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { Stethoscope, Brain, Heart, ArrowRight, ShieldCheck, Lock, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { Specialty } from "@/lib/types";
import AIAvatar from "@/components/AIAvatar";
import clsx from "clsx";

const SPECIALTIES: { label: string; value: Specialty; icon: React.ReactNode; desc: string; color: string }[] = [
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

const FEATURES = [
  { icon: <Zap className="w-4 h-4" />, text: "AI-powered history taking" },
  { icon: <ShieldCheck className="w-4 h-4" />, text: "Clinical-grade accuracy" },
  { icon: <Lock className="w-4 h-4" />, text: "Fully confidential" },
];

const GENDERS = ["Male", "Female", "Other"];

export default function WelcomePage() {
  const router = useRouter();
  const [specialty, setSpecialty] = useState<Specialty>("general_medicine");
  const [language, setLanguage] = useState("");
  const [patientName, setPatientName] = useState("");
  const [patientAge, setPatientAge] = useState("");
  const [patientGender, setPatientGender] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleStart = async () => {
    if (!patientName.trim()) { setError("Patient name is required."); return; }
    if (!patientAge || isNaN(Number(patientAge)) || Number(patientAge) < 1) { setError("A valid age is required."); return; }
    setError("");
    setLoading(true);
    try {
      const data = await api.startConsultation(
        specialty,
        language.trim() || undefined,
        patientName.trim(),
        Number(patientAge),
        patientGender || undefined,
      );
      router.push(`/consultation/${data.session_id}?q=${encodeURIComponent(data.opening_question)}`);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to connect to the server.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex flex-col">
      {/* Hero section — dark gradient with orb */}
      <div className="relative overflow-hidden bg-[#0a0f1e] flex flex-col items-center justify-center px-6 pt-16 pb-20">
        {/* Background glow */}
        <div className="absolute inset-0 pointer-events-none">
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] rounded-full opacity-20"
            style={{ background: "radial-gradient(circle, #4f46e5 0%, #7c3aed 40%, transparent 70%)" }} />
        </div>

        {/* Orb */}
        <div className="float mb-8 relative z-10">
          <AIAvatar speaking={false} size="lg" />
        </div>

        {/* Brand */}
        <div className="relative z-10 text-center mb-6">
          <h1 className="text-4xl font-bold text-white tracking-tight mb-2">
            kuvaka <span className="bg-gradient-to-r from-cyan-400 via-violet-400 to-indigo-400 bg-clip-text text-transparent">Clinical AI</span>
          </h1>
          <p className="text-slate-400 text-base max-w-xs mx-auto leading-relaxed">
            Your AI doctor's assistant — speaks to you, listens, and prepares a complete medical report
          </p>
        </div>

        {/* Feature pills */}
        <div className="relative z-10 flex flex-wrap gap-2 justify-center">
          {FEATURES.map((f, i) => (
            <div key={i} className="flex items-center gap-1.5 bg-white/10 border border-white/10 rounded-full px-3 py-1.5 text-xs text-slate-300 font-medium">
              <span className="text-indigo-400">{f.icon}</span>
              {f.text}
            </div>
          ))}
        </div>
      </div>

      {/* Form section */}
      <div className="flex-1 flex flex-col items-center px-4 py-8 -mt-6 relative z-10">
        <div className="w-full max-w-md space-y-5">

          {/* Patient details card */}
          <div className="card">
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-widest mb-4">
              Patient information
            </h2>
            <div className="space-y-3">
              {/* Name */}
              <div>
                <label className="text-xs font-semibold text-slate-500 block mb-1.5">Full name <span className="text-red-400">*</span></label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="e.g. Aisha Khan"
                  value={patientName}
                  onChange={(e) => setPatientName(e.target.value)}
                />
              </div>

              {/* Age + Gender row */}
              <div className="flex gap-3">
                <div className="w-28 flex-shrink-0">
                  <label className="text-xs font-semibold text-slate-500 block mb-1.5">Age <span className="text-red-400">*</span></label>
                  <input
                    type="number"
                    className="input-field text-center"
                    placeholder="—"
                    min={1}
                    max={120}
                    value={patientAge}
                    onChange={(e) => setPatientAge(e.target.value)}
                  />
                </div>
                <div className="flex-1">
                  <label className="text-xs font-semibold text-slate-500 block mb-1.5">Gender</label>
                  <div className="flex gap-2">
                    {GENDERS.map((g) => (
                      <button
                        key={g}
                        type="button"
                        onClick={() => setPatientGender(patientGender === g ? "" : g)}
                        className={`flex-1 py-2 rounded-lg border text-xs font-semibold transition-all duration-150 ${
                          patientGender === g
                            ? "border-indigo-400 bg-indigo-50 text-indigo-700"
                            : "border-slate-200 bg-white text-slate-500 hover:border-slate-300"
                        }`}
                      >
                        {g}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

            </div>
          </div>

          {/* Specialty card */}
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
                  <span className={clsx(
                    "w-9 h-9 rounded-xl flex items-center justify-center text-white bg-gradient-to-br shadow-sm flex-shrink-0",
                    s.color
                  )}>
                    {s.icon}
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className={clsx("font-semibold text-sm", specialty === s.value ? "text-indigo-700" : "text-gray-800")}>
                      {s.label}
                    </div>
                    <div className="text-xs text-slate-500 mt-0.5">{s.desc}</div>
                  </div>
                  <div className={clsx(
                    "w-5 h-5 rounded-full border-2 flex-shrink-0 flex items-center justify-center transition-all",
                    specialty === s.value ? "border-indigo-600 bg-indigo-600" : "border-slate-300"
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

          {/* Language card */}
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

          {/* CTA */}
          <button
            className="btn-primary w-full text-base py-4 flex items-center justify-center gap-2"
            onClick={handleStart}
            disabled={loading}
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

          <p className="text-center text-xs text-slate-400">
            Powered by kuvaka Clinical AI · For physician use only
          </p>
        </div>
      </div>
    </main>
  );
}
