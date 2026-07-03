"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { api } from "@/lib/api";

const features = [
  "Structured patient history in under 5 minutes",
  "AI-generated differential diagnoses",
  "Instant SOAP note documentation",
];

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await api.login(email.trim(), password);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="min-h-screen flex">
      {/* ── Left: Brand panel ── */}
      <div className="hidden lg:flex lg:w-[420px] xl:w-[480px] bg-brand flex-col justify-between p-12 relative overflow-hidden flex-shrink-0">
        {/* Decorative geometry */}
        <div className="absolute -top-32 -left-32 w-80 h-80 rounded-full border border-white/10 pointer-events-none" />
        <div className="absolute top-1/2 -right-20 w-56 h-56 rounded-full border border-white/10 pointer-events-none" />
        <div className="absolute -bottom-40 left-1/2 -translate-x-1/2 w-[480px] h-[480px] rounded-full border border-white/5 pointer-events-none" />
        <div className="absolute bottom-24 -left-8 w-32 h-32 rounded-full bg-white/5 pointer-events-none" />

        {/* Logo */}
        <div className="relative z-10">
          <img
            src="/kuvaka_logo.png"
            alt="Kuvaka"
            className="h-9 w-auto brightness-0 invert"
          />
        </div>

        {/* Value proposition */}
        <div className="relative z-10 space-y-8">
          <div className="space-y-4">
            <p className="text-white/50 text-xs font-semibold tracking-widest uppercase">
              Clinical AI platform by Kuvaka
            </p>
            <h2 className="font-display text-white text-[2.25rem] font-bold leading-tight">
              Smarter histories.
              <br />
              Better outcomes.
            </h2>
            <p className="text-white/65 text-[0.9375rem] leading-relaxed">
              AI-powered medical history taking that helps you diagnose with
              confidence and document without the burden.
            </p>
          </div>

          <ul className="space-y-3.5">
            {features.map((feat) => (
              <li key={feat} className="flex items-start gap-3">
                <div className="mt-0.5 w-5 h-5 rounded-full bg-white/15 flex items-center justify-center flex-shrink-0">
                  <svg
                    viewBox="0 0 10 10"
                    className="w-3 h-3"
                    fill="none"
                    stroke="white"
                    strokeWidth="1.5"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M1.5 5l2.5 2.5 4.5-4" />
                  </svg>
                </div>
                <span className="text-white/75 text-sm leading-snug">
                  {feat}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* ── Right: Form area ── */}
      <div className="flex-1 flex flex-col justify-center items-center px-8 sm:px-16 bg-white min-h-screen">
        {/* Mobile logo */}
        <div className="lg:hidden mb-10 flex flex-col items-center gap-2">
          <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-9 w-auto" />
          <p className="text-gray-400 text-xs font-medium tracking-wide">
            Clinical AI platform by Kuvaka
          </p>
        </div>

        <div className="w-full max-w-[380px]">
          {/* Heading */}
          <div className="mb-9">
            <h1 className="font-display text-[2rem] font-bold text-gray-900 leading-tight mb-2">
              Welcome back.
            </h1>
            <p className="text-gray-500 text-[0.9375rem]">
              Sign in to your Kuvaka account to continue.
            </p>
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="space-y-5">
            <div className="space-y-1.5">
              <label className="block text-sm font-semibold text-gray-800">
                Email address
              </label>
              <input
                type="email"
                className="input-field"
                placeholder="doctor@hospital.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="email"
              />
            </div>

            <div className="space-y-1.5">
              <label className="block text-sm font-semibold text-gray-800">
                Password
              </label>
              <input
                type="password"
                className="input-field"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm font-medium">
                {error}
              </div>
            )}

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full py-3.5 text-sm flex items-center justify-center gap-2 mt-1"
            >
              {loading ? (
                <>
                  <svg
                    className="animate-spin h-4 w-4"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                  Signing in…
                </>
              ) : (
                "Sign in"
              )}
            </button>
          </form>

          <p className="mt-8 text-center text-sm text-gray-500">
            New to Kuvaka?{" "}
            <Link
              href="/register"
              className="text-brand font-semibold hover:underline underline-offset-2"
            >
              Create an account
            </Link>
          </p>
        </div>
      </div>
    </main>
  );
}
