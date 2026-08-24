"use client";
import { useRouter, useParams } from "next/navigation";
import { useState, useEffect } from "react";
import { Stethoscope, Brain, Heart } from "lucide-react";
import clsx from "clsx";
import { api, getToken } from "@/lib/api";
import type { Patient, Specialty } from "@/lib/types";

const SPECIALTIES: {
  label: string;
  sub: string;
  value: Specialty;
  icon: React.ReactNode;
  iconCls: string;
}[] = [
  {
    label: "सामान्य चिकित्सा",
    sub: "General Medicine",
    value: "general_medicine",
    icon: <Stethoscope className="w-6 h-6" />,
    iconCls: "bg-blue-100 text-blue-600",
  },
  {
    label: "मानसिक स्वास्थ्य",
    sub: "Mental Health",
    value: "psychotherapy",
    icon: <Brain className="w-6 h-6" />,
    iconCls: "bg-violet-100 text-violet-600",
  },
  {
    label: "महिला स्वास्थ्य",
    sub: "Women's Health",
    value: "gynecology",
    icon: <Heart className="w-6 h-6" />,
    iconCls: "bg-rose-100 text-rose-600",
  },
];

const STEPS = ["specialty", "complaint"] as const;
type Step = (typeof STEPS)[number];

// Best-effort location capture — never blocks or fails consultation start.
// Resolves null on denied permission, timeout, or unsupported browser.
function getLocation(): Promise<{ latitude: number; longitude: number } | null> {
  return new Promise((resolve) => {
    if (typeof navigator === "undefined" || !navigator.geolocation) {
      resolve(null);
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ latitude: pos.coords.latitude, longitude: pos.coords.longitude }),
      () => resolve(null),
      { enableHighAccuracy: false, timeout: 5000, maximumAge: 60000 }
    );
  });
}

export default function NewConsultPage() {
  const router = useRouter();
  const params = useParams<{ id: string }>();
  const patientId = params.id;

  const [patient, setPatient] = useState<Patient | null>(null);
  const [stepIndex, setStepIndex] = useState(0);
  const step: Step = STEPS[stepIndex];

  const [specialty, setSpecialty] = useState<Specialty | null>(null);
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

  const goNext = () => {
    setError("");
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  };
  const goBack = () => {
    setError("");
    setStepIndex((i) => Math.max(i - 1, 0));
  };

  const handleStart = async () => {
    setError("");
    setLoading(true);
    try {
      const location = await getLocation();
      const data = await api.startConsultation(
        specialty ?? "general_medicine",
        "Hindi",
        undefined, undefined, undefined,
        chiefComplaint.trim() || undefined,
        patientId,
        location?.latitude,
        location?.longitude,
      );
      router.push(
        `/consultation/${data.session_id}?q=${encodeURIComponent(data.opening_question)}&lang=Hindi`
      );
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to start consultation.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-brand-light to-white flex flex-col px-6 py-10 select-none">
      <div className="w-full flex items-center justify-between">
        <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto" />
        <button
          onClick={() => router.push(`/patients/${patientId}`)}
          className="text-sm text-gray-500 hover:text-gray-800 transition-colors"
        >
          ← Back
        </button>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="w-full max-w-3xl space-y-8 fade-up">
          {/* Patient badge */}
          {patient && (
            <div className="text-center">
              <p className="text-sm font-semibold text-gray-800">{patient.name}</p>
              <p className="text-xs text-gray-400">
                {patient.age} yrs{patient.gender ? ` · ${patient.gender}` : ""}
              </p>
            </div>
          )}

          {/* Step dots */}
          <div className="flex items-center justify-center gap-2">
            {STEPS.map((s, i) => (
              <div
                key={s}
                className={clsx(
                  "h-2.5 rounded-full transition-all",
                  i === stepIndex ? "w-8 bg-brand" : i < stepIndex ? "w-2.5 bg-brand/50" : "w-2.5 bg-gray-200"
                )}
              />
            ))}
          </div>

          <div className="card p-8 space-y-6">
            {/* STEP 1: Type of consultation */}
            {step === "specialty" && (
              <div className="space-y-6">
                <div className="text-center space-y-1">
                  <h2 className="text-xl font-semibold text-gray-900">सलाह का प्रकार चुनें</h2>
                  <p className="text-sm text-gray-500">Choose type of consultation</p>
                </div>

                <div className="space-y-3">
                  {SPECIALTIES.map((s) => (
                    <button
                      key={s.value}
                      type="button"
                      onClick={() => {
                        setSpecialty(s.value);
                        goNext();
                      }}
                      className={clsx(
                        "w-full flex items-center gap-4 p-5 rounded-2xl border-2 text-left transition-all active:scale-[0.98]",
                        specialty === s.value
                          ? "border-brand bg-brand-light"
                          : "border-gray-200 bg-white hover:border-brand/40"
                      )}
                    >
                      <span className={clsx("w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0", s.iconCls)}>
                        {s.icon}
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="font-semibold text-base text-gray-900">{s.label}</div>
                        <div className="text-sm text-gray-400 mt-0.5">{s.sub}</div>
                      </div>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {/* STEP 2: Chief complaint */}
            {step === "complaint" && (
              <div className="space-y-6">
                <div className="text-center space-y-1">
                  <h2 className="text-xl font-semibold text-gray-900">मुख्य समस्या दर्ज करें</h2>
                  <p className="text-sm text-gray-500">
                    Enter chief complaint <span className="text-gray-400">(optional)</span>
                  </p>
                </div>

                <input
                  type="text"
                  autoFocus
                  className="input-field text-center text-lg py-4"
                  placeholder="e.g. chest pain for 2 days, fever since yesterday…"
                  value={chiefComplaint}
                  onChange={(e) => setChiefComplaint(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleStart()}
                />

                {error && (
                  <p className="text-sm text-red-600 bg-red-50 rounded-lg px-4 py-2.5 border border-red-100">
                    {error}
                  </p>
                )}

                <div className="flex gap-3 pt-2">
                  <button type="button" onClick={goBack} className="btn-secondary flex-1 !py-4 text-base">
                    ← Back
                  </button>
                  <button
                    type="button"
                    disabled={loading || !patient}
                    onClick={handleStart}
                    className="btn-primary flex-1 !py-4 text-base flex items-center justify-center gap-2"
                  >
                    {loading ? (
                      <>
                        <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Starting…
                      </>
                    ) : (
                      <>
                        <span>Begin Consultation</span>
                        <span>→</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </main>
  );
}
