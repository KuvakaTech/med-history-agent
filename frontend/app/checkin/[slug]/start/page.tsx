"use client";
import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { ticketApi } from "@/lib/ticketing-api";
import clsx from "clsx";

const LANGUAGES = [
  { code: "hi", label: "हिंदी (Hindi)" },
  { code: "en", label: "English" },
  { code: "mr", label: "मराठी (Marathi)" },
  { code: "gu", label: "ગુજરાતી (Gujarati)" },
  { code: "ta", label: "தமிழ் (Tamil)" },
  { code: "te", label: "తెలుగు (Telugu)" },
];

const GENDERS = [
  { value: "male", label: "Male" },
  { value: "female", label: "Female" },
  { value: "other", label: "Other" },
];

export default function StartPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;

  const [phone, setPhone] = useState("");
  const [language, setLanguage] = useState("hi");
  const [gender, setGender] = useState("male");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleStart = async () => {
    const cleaned = phone.replace(/\D/g, "");
    if (cleaned.length < 10) {
      setError("Please enter a valid phone number.");
      return;
    }
    setError("");
    setLoading(true);
    try {
      const session = await ticketApi.startSession(slug, cleaned, language, gender);
      router.push(`/checkin/${slug}/call/${session.session_id}?lang=${language}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to start. Please try again.");
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen bg-gradient-to-b from-brand-light to-white flex flex-col items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm space-y-8 fade-up">
        {/* Logo / header */}
        <div className="text-center space-y-3">
          <div className="mx-auto w-16 h-16 rounded-2xl bg-brand flex items-center justify-center shadow-lg shadow-brand/30">
            <span className="text-3xl">🏥</span>
          </div>
          <h1 className="text-2xl font-bold text-gray-900">Pre-Visit Check-In</h1>
          <p className="text-sm text-gray-500 leading-relaxed">
            Answer a few quick questions before your appointment so the doctor can see you faster.
          </p>
        </div>

        <div className="card space-y-5">
          {/* Phone */}
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-gray-700">Mobile Number *</label>
            <input
              type="tel"
              className="input-field"
              placeholder="10-digit mobile number"
              value={phone}
              maxLength={15}
              onChange={(e) => setPhone(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleStart()}
            />
            <p className="text-xs text-gray-400">Used to identify your record. No OTP required.</p>
          </div>

          {/* Language */}
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-gray-700">Preferred Language</label>
            <div className="grid grid-cols-2 gap-2">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => setLanguage(l.code)}
                  className={clsx(
                    "px-3 py-2.5 rounded-lg border text-sm font-medium transition-all",
                    language === l.code
                      ? "bg-brand text-white border-brand shadow-sm"
                      : "bg-white text-gray-600 border-gray-200 hover:border-brand/40 hover:text-brand"
                  )}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>

          {/* Gender */}
          <div className="space-y-1.5">
            <label className="text-sm font-semibold text-gray-700">Gender</label>
            <div className="flex gap-2">
              {GENDERS.map((g) => (
                <button
                  key={g.value}
                  type="button"
                  onClick={() => setGender(g.value)}
                  className={clsx(
                    "flex-1 py-2.5 rounded-lg border text-sm font-medium transition-all",
                    gender === g.value
                      ? "bg-brand text-white border-brand"
                      : "bg-white text-gray-600 border-gray-200 hover:border-brand/40"
                  )}
                >
                  {g.label}
                </button>
              ))}
            </div>
          </div>

          {error && (
            <p className="text-sm text-red-600 bg-red-50 rounded-lg px-4 py-2.5 border border-red-100">
              {error}
            </p>
          )}

          <button
            onClick={handleStart}
            disabled={loading || !phone.trim()}
            className="btn-primary w-full flex items-center justify-center gap-2"
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

        <p className="text-center text-xs text-gray-400">
          Your information is kept private and used only for this visit.
        </p>
      </div>
    </main>
  );
}
