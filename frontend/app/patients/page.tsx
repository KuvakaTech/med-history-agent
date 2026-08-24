"use client";
import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, getToken } from "@/lib/api";
import clsx from "clsx";

const GENDERS = [
  { value: "Male", label: "पुरुष", sub: "Male", icon: "👨" },
  { value: "Female", label: "महिला", sub: "Female", icon: "👩" },
];

const KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];

const STEPS = ["name", "age", "gender", "phone"] as const;
type Step = (typeof STEPS)[number];

function DigitKeypad({ onKey }: { onKey: (key: string) => void }) {
  return (
    <div className="grid grid-cols-3 gap-3 max-w-sm mx-auto">
      {KEYPAD_KEYS.map((key) => (
        <button
          key={key}
          type="button"
          onClick={() => onKey(key)}
          className={clsx(
            "h-16 rounded-xl text-xl font-semibold transition-all active:scale-95 flex items-center justify-center",
            key === "clear"
              ? "bg-gray-100 text-gray-500 text-sm"
              : key === "back"
              ? "bg-gray-100 text-gray-600"
              : "bg-white border border-gray-200 text-gray-800 hover:border-brand/40"
          )}
        >
          {key === "clear" ? "Clear" : key === "back" ? "⌫" : key}
        </button>
      ))}
    </div>
  );
}

export default function PatientsPage() {
  const router = useRouter();
  const [checkingAuth, setCheckingAuth] = useState(true);

  const [stepIndex, setStepIndex] = useState(0);
  const step: Step = STEPS[stepIndex];

  const [name, setName] = useState("");
  const [age, setAge] = useState("");
  const [gender, setGender] = useState("");
  const [phone, setPhone] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getToken()
      .catch(() => router.replace("/login"))
      .finally(() => setCheckingAuth(false));
  }, [router]);

  const goNext = () => {
    setError("");
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  };
  const goBack = () => {
    setError("");
    setStepIndex((i) => Math.max(i - 1, 0));
  };

  const pressDigit = (setter: (v: string | ((p: string) => string)) => void, maxLen: number) => (key: string) => {
    if (key === "back") setter((p: string) => p.slice(0, -1));
    else if (key === "clear") setter("");
    else setter((p: string) => (p.length < maxLen ? p + key : p));
  };
  const pressAge = pressDigit(setAge, 2);
  const pressPhone = pressDigit(setPhone, 10);

  // Allow entering digits with a physical keyboard too, not just the on-screen keypad
  useEffect(() => {
    if (step !== "age" && step !== "phone") return;
    const press = step === "age" ? pressAge : pressPhone;
    const canAdvance = step === "age" ? age.length > 0 : phone.length >= 10;
    const handler = (e: KeyboardEvent) => {
      if (e.key >= "0" && e.key <= "9") press(e.key);
      else if (e.key === "Backspace") press("back");
      else if (e.key === "Delete" || e.key === "Escape") press("clear");
      else if (e.key === "Enter" && canAdvance) goNext();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, age, phone]);

  const handleFinish = async () => {
    setError("");
    setCreating(true);
    try {
      const patient = await api.createPatient(
        name.trim(),
        Number(age),
        gender || undefined,
        phone.trim() || undefined
      );
      router.push(`/patients/${patient.patient_id}/consult`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create patient.");
      setCreating(false);
    }
  };

  if (checkingAuth) return null;

  return (
    <main className="min-h-screen bg-gradient-to-b from-brand-light to-white flex flex-col px-6 py-10 select-none">
      <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto self-start" />

      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="w-full max-w-3xl space-y-8 fade-up">
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
            {/* STEP 1: Name */}
            {step === "name" && (
              <div className="space-y-6">
                <div className="text-center space-y-1">
                  <h2 className="text-xl font-semibold text-gray-900">रोगी का नाम दर्ज करें</h2>
                  <p className="text-sm text-gray-500">Enter patient&apos;s full name</p>
                </div>

                <input
                  type="text"
                  autoFocus
                  className="input-field text-center text-xl font-semibold py-4"
                  placeholder="e.g. Rahul Verma"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && name.trim() && goNext()}
                />

                <button
                  type="button"
                  disabled={!name.trim()}
                  onClick={goNext}
                  className="btn-primary w-full !py-4 text-base"
                >
                  Next →
                </button>
              </div>
            )}

            {/* STEP 2: Age */}
            {step === "age" && (
              <div className="space-y-6">
                <div className="text-center space-y-1">
                  <h2 className="text-xl font-semibold text-gray-900">उम्र दर्ज करें</h2>
                  <p className="text-sm text-gray-500">Enter age in years</p>
                </div>

                <div className="flex items-center justify-center gap-2">
                  {Array.from({ length: 2 }).map((_, i) => (
                    <div
                      key={i}
                      className={clsx(
                        "w-14 h-16 rounded-lg border-2 flex items-center justify-center text-2xl font-bold",
                        age[i] ? "border-brand text-gray-900 bg-brand-light/40" : "border-gray-200 text-gray-300"
                      )}
                    >
                      {age[i] ?? ""}
                    </div>
                  ))}
                </div>

                <DigitKeypad onKey={pressAge} />

                <div className="flex gap-3 pt-2">
                  <button type="button" onClick={goBack} className="btn-secondary flex-1 !py-4 text-base">
                    ← Back
                  </button>
                  <button
                    type="button"
                    disabled={!age || Number(age) < 1}
                    onClick={goNext}
                    className="btn-primary flex-1 !py-4 text-base"
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}

            {/* STEP 3: Gender */}
            {step === "gender" && (
              <div className="space-y-6">
                <div className="text-center space-y-1">
                  <h2 className="text-xl font-semibold text-gray-900">लिंग चुनें</h2>
                  <p className="text-sm text-gray-500">Select gender</p>
                </div>

                <div className="grid grid-cols-2 gap-4">
                  {GENDERS.map((g) => (
                    <button
                      key={g.value}
                      type="button"
                      onClick={() => setGender(g.value)}
                      className={clsx(
                        "flex flex-col items-center justify-center gap-2 rounded-2xl border-2 py-10 transition-all active:scale-95",
                        gender === g.value
                          ? "bg-brand text-white border-brand shadow-md"
                          : "bg-white text-gray-700 border-gray-200 hover:border-brand/40"
                      )}
                    >
                      <span className="text-4xl">{g.icon}</span>
                      <span className="text-lg font-semibold">{g.label}</span>
                      <span className="text-xs font-normal opacity-70">{g.sub}</span>
                    </button>
                  ))}
                </div>

                <div className="flex gap-3 pt-2">
                  <button type="button" onClick={goBack} className="btn-secondary flex-1 !py-4 text-base">
                    ← Back
                  </button>
                  <button
                    type="button"
                    disabled={!gender}
                    onClick={goNext}
                    className="btn-primary flex-1 !py-4 text-base"
                  >
                    Next →
                  </button>
                </div>
              </div>
            )}

            {/* STEP 4: Phone */}
            {step === "phone" && (
              <div className="space-y-6">
                <div className="text-center space-y-1">
                  <h2 className="text-xl font-semibold text-gray-900">मोबाइल नंबर दर्ज करें</h2>
                  <p className="text-sm text-gray-500">Enter mobile number</p>
                </div>

                <div className="flex items-center justify-center gap-2">
                  {Array.from({ length: 10 }).map((_, i) => (
                    <div
                      key={i}
                      className={clsx(
                        "w-7 h-11 sm:w-9 sm:h-12 rounded-lg border-2 flex items-center justify-center text-xl font-bold",
                        phone[i] ? "border-brand text-gray-900 bg-brand-light/40" : "border-gray-200 text-gray-300"
                      )}
                    >
                      {phone[i] ?? ""}
                    </div>
                  ))}
                </div>

                <DigitKeypad onKey={pressPhone} />

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
                    disabled={creating || phone.length < 10}
                    onClick={handleFinish}
                    className="btn-primary flex-1 !py-4 text-base flex items-center justify-center gap-2"
                  >
                    {creating ? (
                      <>
                        <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Creating…
                      </>
                    ) : (
                      <>
                        <span>Start Consultation</span>
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
