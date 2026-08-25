"use client";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { kioskApi } from "@/lib/kiosk-api";
import type {
  GrievanceAddress,
  GrievanceResultResponse,
  KioskTranscriptEntry,
} from "@/lib/kiosk-types";
import clsx from "clsx";

function formatAddress(addr: GrievanceAddress | null | undefined): string {
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

export default function KioskResultPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;

  const [result, setResult] = useState<GrievanceResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const printRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    kioskApi
      .getResult(slug, sessionId)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug, sessionId]);

  useEffect(() => {
    if (slug === "varanasi-nagar-nigam") {
      document.title = "Varanasi Nagar Nigam";
    } else if (slug === "varanasi-jan-sunwai") {
      document.title = "वाराणसी जन सुनवाई";
    } else {
      return;
    }
    return () => {
      document.title = "Community Health Assistant";
    };
  }, [slug]);

  if (loading) {
    return (
      <main className="min-h-screen flex items-center justify-center bg-gray-50">
        <p className="text-gray-500">लोड हो रहा है…</p>
      </main>
    );
  }

  if (error || !result) {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center gap-4 px-6">
        <p className="text-red-600">{error || "Result not found"}</p>
        <button
          type="button"
          className="btn-primary"
          onClick={() => router.push(`/kiosk/${slug}/start`)}
        >
          नई शिकायत
        </button>
      </main>
    );
  }

  const g = result.grievance;
  const isPartial = result.status === "partial";

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-5 h-14 flex items-center justify-between sticky top-0 z-50 print:hidden">
        <span className="text-sm font-semibold text-gray-700">शिकायत पर्ची</span>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => window.print()}
            className="btn-secondary text-xs py-2 px-3"
          >
            Print
          </button>
          <button
            type="button"
            onClick={() => router.push(`/kiosk/${slug}/start`)}
            className="btn-primary text-xs py-2 px-3"
          >
            नई शिकायत
          </button>
        </div>
      </header>

      <div ref={printRef} className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <div className="text-center space-y-2">
          {slug === "varanasi-nagar-nigam" ? (
            <p className="text-lg font-extrabold text-orange-600">वाराणसी नगर निगम</p>
          ) : slug === "varanasi-jan-sunwai" ? (
            <p className="text-lg font-extrabold text-orange-600">वाराणसी जन सुनवाई</p>
          ) : (
            <p className="text-sm text-gray-500">{result.centre_name || "Jan Sunwai"}</p>
          )}
          <h1 className="text-xl font-bold text-gray-900">
            {isPartial ? "अधूरी शिकायत" : "शिकायत दर्ज हो गई"}
          </h1>
          {result.complaint_number && (
            <p className="text-3xl font-mono font-bold text-amber-700 tracking-wide">
              {result.complaint_number}
            </p>
          )}
          {isPartial && (
            <p className="text-sm text-amber-700 bg-amber-50 rounded-lg py-2 px-4">
              बातचीत पूरी नहीं हुई — कर्मचारी काउंटर पर सहायता लें।
            </p>
          )}
        </div>

        {g && (
          <div className="bg-white rounded-2xl border border-gray-100 shadow-sm divide-y divide-gray-100">
            <Section title="नाम" value={g.full_name} />
            <Section title="पिता / पति / अभिभावक" value={g.father_guardian_name} />
            <Section title="श्रेणी" value={g.category} sub={g.sub_category} />
            <Section title="विभाग" value={g.department_tag} />
            <Section title="तात्कालिकता" value={g.urgency} />
            <Section title="समस्या" value={g.confirmed_summary || g.verbatim_problem} />
            <Section title="कब से" value={g.since_when} />
            <Section title="प्रभावित" value={g.affected_count} />
            <Section title="पहले क्या किया" value={g.prior_action} />
            <Section title="आप क्या चाहते हैं" value={g.desired_outcome} />
            <Section title="पता (घर)" value={formatAddress(g.residential_address)} />
            {!g.complaint_location_same_as_home && (
              <Section title="शिकायत का स्थान" value={formatAddress(g.complaint_address)} />
            )}
          </div>
        )}

        {(result.transcript?.length ?? 0) > 0 && (
          <TranscriptSection entries={result.transcript!} />
        )}

        <div className="text-center text-xs text-gray-400 print:hidden">
          <p>Started: {result.started_at || "—"}</p>
          <p>Ended: {result.ended_at || "—"}</p>
          <p>Phone (intake): {result.phone}</p>
        </div>
      </div>
    </main>
  );
}

function Section({
  title,
  value,
  sub,
}: {
  title: string;
  value?: string | null;
  sub?: string | null;
}) {
  if (!value && !sub) return null;
  return (
    <div className="px-5 py-4">
      <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">{title}</p>
      <p className="text-gray-900 mt-1">{value || "—"}</p>
      {sub && <p className="text-sm text-gray-500 mt-0.5">{sub}</p>}
    </div>
  );
}

function TranscriptSection({ entries }: { entries: KioskTranscriptEntry[] }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm p-5 space-y-4 print:hidden">
      <h2 className="text-base font-bold text-gray-900">पूरी बातचीत</h2>
      <div className="space-y-3 max-h-[28rem] overflow-y-auto">
        {entries.map((entry, i) => {
          const isUser = entry.speaker === "user";
          return (
            <div
              key={i}
              className={clsx(
                "rounded-2xl p-4 border",
                isUser
                  ? "bg-amber-50 border-amber-100"
                  : "bg-white border-gray-100 shadow-sm"
              )}
            >
              <p
                className={clsx(
                  "text-xs font-medium mb-1",
                  isUser ? "text-amber-700" : "text-gray-400"
                )}
              >
                {isUser ? "आप" : "AI सहायक"}
              </p>
              <p className="text-gray-800 leading-relaxed">{entry.text}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
