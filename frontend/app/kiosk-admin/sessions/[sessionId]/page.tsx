"use client";
import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { kioskAdminApi } from "@/lib/kiosk-admin-api";
import type { KioskAdminSessionDetail, KioskCentre } from "@/lib/kiosk-admin-types";
import { getToken } from "@/lib/api";
import clsx from "clsx";

function formatAddress(addr: Record<string, unknown> | null | undefined): string {
  if (!addr) return "—";
  const parts = [
    addr.house,
    addr.street,
    addr.village_mohalla,
    addr.gp_ward,
    addr.tehsil,
    addr.block,
    addr.post_office,
    addr.pin_code,
    addr.landmark,
  ].filter(Boolean);
  return parts.length ? parts.join(", ") : "—";
}

export default function KioskAdminSessionPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.sessionId as string;

  const [session, setSession] = useState<KioskAdminSessionDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [userRole, setUserRole] = useState("");
  const [centres, setCentres] = useState<KioskCentre[]>([]);

  useEffect(() => {
    getToken()
      .then(async (t) => {
        const payload = JSON.parse(atob(t.split(".")[1]));
        const role = payload.role;
        if (role !== "centre_admin" && role !== "super_admin") {
          router.push("/kiosk-admin/login");
          return;
        }
        setUserRole(role);
        const [sessionData] = await Promise.all([
          kioskAdminApi.getSession(t, sessionId, null),
          role === "super_admin"
            ? kioskAdminApi.listCentres(t).then((r) => setCentres(r.centres))
            : Promise.resolve(),
        ]);
        setSession(sessionData);
      })
      .catch((e) => {
        if (e.message?.includes("401") || e.message === "refresh_failed") {
          router.push("/kiosk-admin/login");
        } else {
          setError(e.message);
        }
      })
      .finally(() => setLoading(false));
  }, [sessionId, router]);

  const sessionCentre = centres.find((c) => c.centre_id === session?.centre_id);
  const g = session?.grievance as Record<string, unknown> | null | undefined;

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500 text-sm">Loading…</p>
      </main>
    );
  }
  if (error) return <p className="p-8 text-red-600 text-sm">{error}</p>;
  if (!session) return null;

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-6 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => router.push("/kiosk-admin")}
            className="text-sm text-gray-500 hover:text-amber-700"
          >
            ← Grievances
          </button>
          {userRole === "super_admin" && (
            <span className="px-2 py-1 bg-purple-100 text-purple-700 text-xs font-semibold rounded-full">
              Super Admin
            </span>
          )}
        </div>
        {(session.centre_name || sessionCentre) && (
          <span className="text-xs font-semibold text-gray-500">
            {session.centre_name || sessionCentre?.name}
          </span>
        )}
      </header>

      <div className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <div className="text-center space-y-2">
          {session.complaint_number && (
            <p className="text-3xl font-mono font-bold text-amber-700 tracking-wide">
              {session.complaint_number}
            </p>
          )}
          <p className="text-sm text-gray-500">
            {session.started_at_ist || "—"} · Phone: {session.phone}
          </p>
          <span
            className={clsx(
              "inline-block text-xs font-semibold px-2 py-1 rounded-full",
              session.status === "completed" && "bg-green-100 text-green-700",
              session.status === "partial" && "bg-amber-100 text-amber-700",
              session.status === "active" && "bg-blue-100 text-blue-700"
            )}
          >
            {session.status}
          </span>
        </div>

        {g && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm divide-y divide-gray-100">
            {[
              ["Name", g.full_name],
              ["Father / Guardian", g.father_guardian_name],
              ["Category", g.category],
              ["Department", g.department_tag],
              ["Urgency", g.urgency],
              ["Problem", g.confirmed_summary || g.verbatim_problem],
              ["Since", g.since_when],
              ["Desired outcome", g.desired_outcome],
              ["Address", formatAddress(g.residential_address as Record<string, unknown>)],
            ].map(([label, value]) =>
              value ? (
                <div key={label as string} className="px-5 py-4">
                  <p className="text-xs font-semibold text-gray-400 uppercase">{label}</p>
                  <p className="text-gray-900 mt-1">{String(value)}</p>
                </div>
              ) : null
            )}
          </div>
        )}

        {(session.transcript?.length ?? 0) > 0 && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-4">
            <h2 className="text-base font-bold text-gray-900">पूरी बातचीत</h2>
            <div className="space-y-3 max-h-[28rem] overflow-y-auto">
              {session.transcript!.map((entry, i) => {
                const isUser = entry.speaker === "user";
                return (
                  <div
                    key={i}
                    className={clsx(
                      "rounded-2xl p-4 border",
                      isUser ? "bg-amber-50 border-amber-100" : "bg-white border-gray-100"
                    )}
                  >
                    <p className={clsx("text-xs font-medium mb-1", isUser ? "text-amber-700" : "text-gray-400")}>
                      {isUser ? "आप" : "AI सहायक"}
                    </p>
                    <p className="text-gray-800 leading-relaxed">{entry.text}</p>
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>
    </main>
  );
}
