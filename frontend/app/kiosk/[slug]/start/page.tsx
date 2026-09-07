"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { kioskApi } from "@/lib/kiosk-api";
import type { CentreResponse, LessonTopic } from "@/lib/kiosk-types";
import { LESSON_TOPICS, isBarwaniJanSunwaiSlug, isJanSunwaiSlug } from "@/lib/kiosk-types";
import clsx from "clsx";

const GENDERS = [
  { value: "male", label: "पुरुष", sub: "Male", icon: "👨" },
  { value: "female", label: "महिला", sub: "Female", icon: "👩" },
];

const KEYPAD_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "clear", "0", "back"];

const GRIEVANCE_STEPS = ["phone", "gender"] as const;
type GrievanceStep = (typeof GRIEVANCE_STEPS)[number];

const LEARNING_STEPS = ["name", "topic"] as const;
type LearningStep = (typeof LEARNING_STEPS)[number];

function centreInitials(name: string): string {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (words.length >= 2) {
    return (words[0][0] + words[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

function usePageTitle(slug: string) {
  useEffect(() => {
    if (slug === "varanasi-nagar-nigam") {
      document.title = "Varanasi Nagar Nigam";
    } else if (isJanSunwaiSlug(slug)) {
      document.title = "वाराणसी जन सुनवाई";
    } else if (isBarwaniJanSunwaiSlug(slug)) {
      document.title = "बड़वानी जन सुनवाई";
    } else if (slug === "barwani-guddi") {
      document.title = "गुड्डी";
    } else {
      return;
    }
    return () => {
      document.title = "Community Health Assistant";
    };
  }, [slug]);
}

export default function KioskStartPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;

  const [centre, setCentre] = useState<CentreResponse | null>(null);
  const [centreError, setCentreError] = useState("");
  const [loadingCentre, setLoadingCentre] = useState(true);

  usePageTitle(slug);

  useEffect(() => {
    kioskApi
      .getCentre(slug)
      .then(setCentre)
      .catch((e) => setCentreError(e.message))
      .finally(() => setLoadingCentre(false));
  }, [slug]);

  if (loadingCentre) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gradient-to-b from-amber-50 to-white">
        <p className="text-gray-500">लोड हो रहा है…</p>
      </main>
    );
  }

  if (centreError || !centre) {
    return (
      <main className="min-h-screen flex items-center justify-center px-6">
        <p className="text-red-600">{centreError || "Centre not found"}</p>
      </main>
    );
  }

  if (centre.centre_kind === "learning") {
    return <LearningStart slug={slug} centre={centre} router={router} />;
  }

  return <GrievanceStart slug={slug} centre={centre} router={router} />;
}

function LearningStart({
  slug,
  centre,
  router,
}: {
  slug: string;
  centre: CentreResponse;
  router: ReturnType<typeof useRouter>;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const step: LearningStep = LEARNING_STEPS[stepIndex];
  const [learnerName, setLearnerName] = useState("");
  const [selectedTopic, setSelectedTopic] = useState<LessonTopic | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleStart = async (topic: LessonTopic) => {
    setError("");
    setLoading(true);
    try {
      const session = await kioskApi.startSession(slug, {
        language: centre.default_language,
        learner_name: learnerName.trim() || undefined,
        lesson_topic: topic,
      });
      router.push(`/kiosk/${slug}/call/${session.session_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start. Please try again.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-pink-50 via-purple-50 to-white flex flex-col px-6 py-10 select-none">
      <div className="flex items-center gap-3 self-start">
        <div className="h-12 w-12 rounded-full bg-pink-400 text-white flex items-center justify-center text-xl">
          🌸
        </div>
        <div>
          <p className="text-lg font-extrabold text-pink-600">गुड्डी</p>
          <p className="text-xs text-purple-500">{centre.name}</p>
        </div>
      </div>

      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="w-full max-w-3xl space-y-8 fade-up">
          <div className="text-center space-y-3">
            <div className="flex items-center justify-center gap-2 pt-2">
              {LEARNING_STEPS.map((s, i) => (
                <div
                  key={s}
                  className={clsx(
                    "h-2 w-2 rounded-full",
                    i <= stepIndex ? "bg-pink-500" : "bg-gray-200"
                  )}
                />
              ))}
            </div>
            <h1 className="text-2xl font-bold text-gray-900">हिंदी सीखें!</h1>
            <p className="text-sm text-gray-500">Learn Hindi with Guddi</p>
          </div>

          {step === "name" && (
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-lg font-medium text-gray-800">तुम्हारा नाम क्या है?</p>
                <p className="text-sm text-gray-400 mt-1">Optional — skip if you like</p>
              </div>
              <input
                type="text"
                value={learnerName}
                onChange={(e) => setLearnerName(e.target.value)}
                placeholder="जैसे — कविता"
                className="w-full max-w-sm mx-auto block text-center text-2xl font-semibold border-2 border-pink-200 rounded-2xl py-4 px-4 focus:border-pink-400 focus:outline-none"
                maxLength={30}
              />
              <div className="max-w-xs mx-auto flex flex-col gap-3">
                <button
                  type="button"
                  onClick={() => setStepIndex(1)}
                  className="w-full py-4 rounded-xl font-semibold text-white bg-pink-500 hover:bg-pink-600 transition-all active:scale-[0.98]"
                >
                  आगे बढ़ें →
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setLearnerName("");
                    setStepIndex(1);
                  }}
                  className="text-sm text-gray-400 hover:text-gray-600"
                >
                  नाम नहीं बताना →
                </button>
              </div>
            </div>
          )}

          {step === "topic" && (
            <div className="space-y-6">
              <div className="text-center">
                <p className="text-lg font-medium text-gray-800">आज क्या सीखेंगे?</p>
                <p className="text-sm text-gray-400 mt-1">Pick a topic</p>
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 max-w-lg mx-auto">
                {LESSON_TOPICS.map((t) => (
                  <button
                    key={t.value}
                    type="button"
                    disabled={loading}
                    onClick={() => {
                      setSelectedTopic(t.value);
                      void handleStart(t.value);
                    }}
                    className={clsx(
                      "flex flex-col items-center gap-2 rounded-2xl border-2 py-4 px-2 transition-all active:scale-95",
                      selectedTopic === t.value
                        ? "border-pink-400 bg-pink-50"
                        : "border-gray-200 bg-white hover:border-pink-300"
                    )}
                  >
                    <div className="w-20 h-20 rounded-xl overflow-hidden bg-pink-50 flex items-center justify-center">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={t.coverImage}
                        alt={t.label}
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <span className="text-sm font-semibold text-gray-800">{t.label}</span>
                  </button>
                ))}
              </div>
              <div className="max-w-xs mx-auto">
                <button
                  type="button"
                  onClick={() => setStepIndex(0)}
                  className="btn-secondary w-full !py-4 text-base"
                >
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

function GrievanceStart({
  slug,
  centre,
  router,
}: {
  slug: string;
  centre: CentreResponse;
  router: ReturnType<typeof useRouter>;
}) {
  const [stepIndex, setStepIndex] = useState(0);
  const step: GrievanceStep = GRIEVANCE_STEPS[stepIndex];
  const [phone, setPhone] = useState("");
  const [language] = useState("hi");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const centreInitialsLabel = centreInitials(centre.name);

  const goNext = () => {
    setError("");
    setStepIndex((i) => Math.min(i + 1, GRIEVANCE_STEPS.length - 1));
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
      const session = await kioskApi.startSession(slug, {
        phone: cleaned,
        language,
        gender: finalGender,
      });
      router.push(`/kiosk/${slug}/call/${session.session_id}?lang=${language}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start. Please try again.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-amber-50 to-white flex flex-col px-6 py-10 select-none">
      {slug === "varanasi-nagar-nigam" ? (
        <div className="flex flex-col self-start leading-tight">
          <span className="text-xl font-extrabold text-orange-600">वाराणसी नगर निगम</span>
          <span className="text-xs font-bold text-orange-500 tracking-widest">VARANASI NAGAR NIGAM</span>
        </div>
      ) : isJanSunwaiSlug(slug) ? (
        <div className="flex flex-col self-start leading-tight">
          <span className="text-xl font-extrabold text-orange-600">वाराणसी जन सुनवाई</span>
          <span className="text-xs font-bold text-orange-500 tracking-widest">VARANASI JAN SUNWAI</span>
        </div>
      ) : isBarwaniJanSunwaiSlug(slug) ? (
        <div className="flex flex-col self-start leading-tight">
          <span className="text-xl font-extrabold text-orange-600">बड़वानी जन सुनवाई</span>
          <span className="text-xs font-bold text-orange-500 tracking-widest">BARWANI JAN SUNWAI</span>
        </div>
      ) : (
        <div className="flex items-center gap-3 self-start">
          <div className="h-10 w-10 rounded-full bg-amber-600 text-white flex items-center justify-center text-sm font-bold">
            {centreInitialsLabel}
          </div>
          <div>
            <p className="text-sm font-semibold text-gray-900">{centre.name}</p>
            <p className="text-xs text-gray-500">{centre.name}</p>
          </div>
        </div>
      )}

      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="w-full max-w-3xl space-y-8 fade-up">
          <div className="text-center space-y-3">
            <div className="flex items-center justify-center gap-2 pt-2">
              {GRIEVANCE_STEPS.map((s, i) => (
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
                  className="w-full !py-4 text-base rounded-lg font-semibold text-white bg-amber-600 hover:bg-amber-700 transition-all active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed"
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
