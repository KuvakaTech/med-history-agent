"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { kioskApi } from "@/lib/kiosk-api";
import clsx from "clsx";

const GENDERS = [
  { value: "male", label: "पुरुष", sub: "Male", icon: "👨" },
  { value: "female", label: "महिला", sub: "Female", icon: "👩" },
];

const KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];

const STEPS = ["phone", "gender"] as const;
type Step = (typeof STEPS)[number];

function centreInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

export default function KioskStartPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;

  const [stepIndex, setStepIndex] = useState(0);
  const step: Step = STEPS[stepIndex];
  const [phone, setPhone] = useState("");
  const [language] = useState("hi");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [centreName, setCentreName] = useState("");
  const [centreInitialsLabel, setCentreInitialsLabel] = useState("");

  useEffect(() => {
    kioskApi
      .getCentre(slug)
      .then((c) => {
        setCentreName(c.name);
        setCentreInitialsLabel(centreInitials(c.name));
      })
      .catch(() => {
        setCentreName(slug);
        setCentreInitialsLabel(slug.slice(0, 2).toUpperCase());
      });
  }, [slug]);

  const goNext = () => {
    setError("");
    setStepIndex((i) => Math.min(i + 1, STEPS.length - 1));
  };
  const goBack = () => {
    setError("");
    setStepIndex((i) => Math.max(i - 1, 0));
  };

  const pressKey = (key: string) => {
    if (key === "back") setPhone((p) => p.slice(0, -1));
    else if (key === "clear") setPhone("");
    else setPhone((p) => (p.length < 10 ? p + key : p));
  };

  useEffect(() => {
    if (step !== "phone") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key >= "0" && e.key <= "9") pressKey(e.key);
      else if (e.key === "Backspace") pressKey("back");
      else if (e.key === "Delete" || e.key === "Escape") setPhone("");
      else if (e.key === "Enter" && phone.length >= 10) goNext();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [step, phone]);

  const handleStart = async (finalGender: string) => {
    const cleaned = phone.replace(/\D/g, "");
    setError("");
    setLoading(true);
    try {
      const session = await kioskApi.startSession(slug, cleaned, language, finalGender);
      router.push(`/kiosk/${slug}/call/${session.session_id}?lang=${language}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start. Please try again.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-amber-50 to-white flex flex-col px-6 py-10 select-none">
      <div className="flex items-center gap-3 self-start">
        <div className="h-10 w-10 rounded-full bg-amber-600 text-white flex items-center justify-center text-sm font-bold">
          {centreInitialsLabel || "—"}
        </div>
        <div>
          <p className="text-sm font-semibold text-gray-900">{centreName || "शिकायत कियोस्क"}</p>
          <p className="text-xs text-gray-500">Varanasi</p>
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="w-full max-w-3xl space-y-8 fade-up">
          <div className="text-center space-y-3">
            <div className="flex items-center justify-center gap-2 pt-2">
              {STEPS.map((s, i) => (
                <div
                  key={s}
                  className={clsx(
                    "h-2 w-2 rounded-full",
                    i <= stepIndex ? "bg-amber-600" : "bg-gray-200"
                  )}
                />
              ))}
            </div>
            <h1 className="text-2xl font-bold text-gray-900">शिकायत दर्ज करें</h1>
            <p className="text-sm text-gray-500">Register your grievance at the kiosk</p>
          </div>

          {step === "phone" && (
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-lg font-medium text-gray-800">मोबाइल नंबर दर्ज करें</p>
                <p className="text-sm text-gray-400 mt-1">Enter your mobile number</p>
                <p className="text-3xl font-mono font-bold text-gray-900 mt-4 tracking-widest">
                  {phone || "—"}
                </p>
              </div>
              <div className="grid grid-cols-3 gap-3 max-w-xs mx-auto">
                {KEYPAD_KEYS.map((key) => (
                  <button
                    key={key}
                    type="button"
                    onClick={() => pressKey(key)}
                    className={clsx(
                      "h-14 rounded-xl text-lg font-semibold transition-all active:scale-95",
                      key === "clear" || key === "back"
                        ? "bg-gray-100 text-gray-600"
                        : "bg-white border-2 border-gray-200 text-gray-800 hover:border-amber-400"
                    )}
                  >
                    {key === "clear" ? "C" : key === "back" ? "⌫" : key}
                  </button>
                ))}
              </div>
              <div className="max-w-xs mx-auto">
                <button
                  type="button"
                  disabled={phone.length < 10}
                  onClick={goNext}
                  className="btn-primary w-full !py-4 text-base disabled:opacity-40"
                >
                  आगे बढ़ें →
                </button>
              </div>
            </div>
          )}

          {step === "gender" && (
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-lg font-medium text-gray-800">लिंग चुनें</p>
                <p className="text-sm text-gray-400">Select gender</p>
              </div>
              <div className="grid grid-cols-2 gap-4 max-w-md mx-auto">
                {GENDERS.map((g) => (
                  <button
                    key={g.value}
                    type="button"
                    disabled={loading}
                    onClick={() => handleStart(g.value)}
                    className="flex flex-col items-center gap-2 rounded-2xl border-2 border-gray-200 bg-white py-10 transition-all active:scale-95 hover:border-amber-400"
                  >
                    <span className="text-3xl">{g.icon}</span>
                    <span className="text-base font-semibold">{g.label}</span>
                    <span className="text-xs text-gray-400">{g.sub}</span>
                  </button>
                ))}
              </div>
              <div className="max-w-xs mx-auto">
                <button type="button" onClick={goBack} className="btn-secondary w-full !py-4 text-base">
                  ← वापस
                </button>
              </div>
            </div>
          )}

          {error && (
            <p className="text-center text-sm text-red-600 bg-red-50 rounded-lg py-2 px-4">
              {error}
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
