"use client";
import { useEffect } from "react";
import Link from "next/link";

const CARDS = [
  {
    title: "Office of District Magistrate Varanasi",
    sub: "Public grievance kiosk",
    href: "/kiosk/varanasi-jan-sunwai/start",
    icon: "🗣️",
  },
  {
    title: "Nagar Nigam",
    sub: "Municipal corporation kiosk",
    href: "/kiosk/varanasi-nagar-nigam/start",
    icon: "🏛️",
  },
  {
    title: "Hospital Platform",
    sub: "Hospital staff login",
    href: "/login",
    icon: "🏥",
  },
];

const ADMIN_LINKS = [
  { label: "Hospital Admin", href: "/login?to=admin" },
  { label: "Nagar Nigam Admin", href: "/kiosk-admin/login" },
  { label: "Jan Sunvai Admin", href: "/kiosk-admin/login" },
];

export default function DashboardPage() {
  useEffect(() => {
    document.title = "Dashboard";
  }, []);

  return (
    <main className="min-h-screen bg-gradient-to-b from-brand-light to-white flex flex-col px-6 py-10">
      <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-6 w-auto self-start" />

      <div className="flex-1 flex flex-col items-center justify-center">
        <div className="w-full max-w-4xl space-y-10 fade-up">
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-semibold text-gray-900">Select a Service</h1>
            <p className="text-sm text-gray-500">Choose where you&apos;d like to go</p>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-5">
            {CARDS.map((c) => (
              <Link
                key={c.href}
                href={c.href}
                target="_blank"
                rel="noopener noreferrer"
                className="card flex flex-col items-center justify-center gap-3 py-12 px-6 text-center border-2 border-gray-200 hover:border-brand/40 hover:shadow-md transition-all active:scale-[0.98]"
              >
                <span className="text-4xl">{c.icon}</span>
                <div className="space-y-1">
                  <p className="text-lg font-semibold text-gray-900">{c.title}</p>
                  <p className="text-xs text-gray-400">{c.sub}</p>
                </div>
              </Link>
            ))}
          </div>

          <div className="flex items-center justify-center gap-6 pt-4 flex-wrap">
            {ADMIN_LINKS.map((l) => (
              <Link
                key={l.label}
                href={l.href}
                target="_blank"
                rel="noopener noreferrer"
                className="text-xs font-semibold text-gray-400 hover:text-brand transition-colors underline underline-offset-2"
              >
                {l.label}
              </Link>
            ))}
          </div>
        </div>
      </div>
    </main>
  );
}
