"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ticketApi } from "@/lib/ticketing-api";
import clsx from "clsx";

const LANGUAGES = [
  { code: "hi", label: "हिंदी", sub: "Hindi" },
  { code: "en", label: "English", sub: "अंग्रेज़ी" },
  { code: "mr", label: "मराठी", sub: "Marathi" },
  { code: "gu", label: "ગુજરાતી", sub: "Gujarati" },
  { code: "ta", label: "தமிழ்", sub: "Tamil" },
  { code: "te", label: "తెలుగు", sub: "Telugu" },
];

const GENDERS = [
  { value: "male", label: "पुरुष", sub: "Male", icon: "👨" },
  { value: "female", label: "महिला", sub: "Female", icon: "👩" },
];

const KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];

const STEPS = ["language", "phone", "gender"] as const;
type Step = (typeof STEPS)[number];

export default function StartPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;

  const [stepIndex, setStepIndex] = useState(0);
  const step: Step = STEPS[stepIndex];

  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("");
  const [gender, setGender] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const goNext = () => {
    setError("");
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  };
  const goBack = () => {
    setError("");
    setStepIndex((i) => Math.max(i - 1, 0));
  };

  const pressKey = (key: string) => {
    if (key === "back") {
      setPhone((p) => p.slice(0, -1));
    } else if (key === "clear") {
      setPhone("");
    } else {
      setPhone((p) => (p.length < 10 ? p + key : p));
    }
  };

  // Allow entering the phone number with a physical keyboard, not just the on-screen keypad
  useEffect(() => {
    if (step !== "phone") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key >= "0" && e.key <= "9") {
        pressKey(e.key);
      } else if (e.key === "Backspace") {
        pressKey("back");
      } else if (e.key === "Delete" || e.key === "Escape") {
        setPhone("");
      } else if (e.key === "Enter" && phone.length >= 10) {
        goNext();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [step, phone]);

  const handleStart = async (finalGender: string) => {
    const cleaned = phone.replace(/\D/g, "");
    setError("");
    setLoading(true);
    try {
      const session = await ticketApi.startSession(slug, cleaned, language, finalGender);
      router.push(`/checkin/${slug}/call/${session.session_id}?lang=${language}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start. Please try again.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-brand-light to-white flex flex-col px-6 py-10 select-none">
      <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto self-start" />

      <div className="flex-1 flex flex-col items-center justify-center">
      <div className="w-full max-w-3xl space-y-8 fade-up">
        {/* Header */}
        <div className="text-center space-y-3">
          {/* Step dots */}
          <div className="flex items-center justify-center gap-2 pt-2">
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
        </div>

        <div className="card p-8 space-y-6">
          {/* STEP 1: Language */}
          {step === "language" && (
            <div className="space-y-6">
              <div className="text-center space-y-1">
                <h2 className="text-xl font-semibold text-gray-900">भाषा चुनें</h2>
                <p className="text-sm text-gray-500">Choose your language</p>
              </div>
              <div className="grid grid-cols-3 gap-4">
                {LANGUAGES.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    onClick={() => {
                      setLanguage(l.code);
                      goNext();
                    }}
                    className={clsx(
                      "flex flex-col items-center justify-center gap-1 rounded-2xl border-2 py-8 text-lg font-semibold transition-all active:scale-95",
                      language === l.code
                        ? "bg-brand text-white border-brand shadow-md"
                        : "bg-white text-gray-700 border-gray-200 hover:border-brand/40 hover:text-brand"
                    )}
                  >
                    <span>{l.label}</span>
                    <span className="text-xs font-normal opacity-70">{l.sub}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* STEP 2: Phone number */}
          {step === "phone" && (
            <div className="space-y-6">
              <div className="text-center space-y-1">
                <h2 className="text-xl font-semibold text-gray-900">मोबाइल नंबर दर्ज करें</h2>
                <p className="text-sm text-gray-500">Enter your 10-digit mobile number</p>
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

              <div className="grid grid-cols-3 gap-3 max-w-sm mx-auto">
                {KEYPAD_KEYS.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => pressKey(key)}
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

              <div className="flex gap-3 pt-2">
                <button type="button" onClick={goBack} className="btn-secondary flex-1 !py-4 text-base">
                  ← Back
                </button>
                <button
                  type="button"
                  disabled={phone.length < 10}
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
                <p className="text-sm text-gray-500">Select your gender</p>
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
                  disabled={loading || !gender}
                  onClick={() => handleStart(gender)}
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
                      <span>Start Check-In</span>
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
