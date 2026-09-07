"use client";
import { Suspense, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { kioskApi } from "@/lib/kiosk-api";
import type {
  GrievanceAddress,
  KioskTranscriptEntry,
  SessionResultResponse,
} from "@/lib/kiosk-types";
import { isJanSunwaiSlug } from "@/lib/kiosk-types";
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

const RESULT_LABEL: Record<string, string> = {
  clear: "साफ ✅",
  emerging: "लगभग 🌱",
  not_yet: "अभी नहीं ⏳",
};

export default function KioskResultPage() {
  return (
    <Suspense fallback={null}>
      <KioskResultPageInner />
    </Suspense>
  );
}

function KioskResultPageInner() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;
  const autoprint = searchParams.get("autoprint") === "1";

  const [result, setResult] = useState<SessionResultResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [countdown, setCountdown] = useState<number | null>(null);
  const printRef = useRef<HTMLDivElement>(null);
  const printTriggeredRef = useRef(false);
  const countdownStartedRef = useRef(false);

  const isLearning = result?.centre_kind === "learning";

  useEffect(() => {
    kioskApi
      .getResult(slug, sessionId)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [slug, sessionId]);

  useEffect(() => {
    if (!result || !autoprint || isLearning || countdownStartedRef.current) return;
    countdownStartedRef.current = true;
    setCountdown(5);
  }, [result, autoprint, isLearning]);

  useEffect(() => {
    if (countdown === null) return;
    if (countdown === 0) {
      printTriggeredRef.current = true;
      setCountdown(null);
      window.print();
      return;
    }
    const t = setTimeout(() => setCountdown((c) => (c !== null ? c - 1 : c)), 1000);
    return () => clearTimeout(t);
  }, [countdown]);

  useEffect(() => {
    if (!autoprint || isLearning) return;
    const handleAfterPrint = () => {
      if (printTriggeredRef.current) {
        router.replace(`/kiosk/${slug}/start`);
      }
    };
    window.addEventListener("afterprint", handleAfterPrint);
    return () => window.removeEventListener("afterprint", handleAfterPrint);
  }, [autoprint, slug, router, isLearning]);

  useEffect(() => {
    if (slug === "varanasi-nagar-nigam") {
      document.title = "Varanasi Nagar Nigam";
    } else if (isJanSunwaiSlug(slug)) {
      document.title = "वाराणसी जन सुनवाई";
    } else if (slug === "barwani-guddi") {
      document.title = "गुड्डी";
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
          {slug === "barwani-guddi" ? "नया सबक" : "नई शिकायत"}
        </button>
      </main>
    );
  }

  if (isLearning) {
    return (
      <LearningResultView
        slug={slug}
        result={result}
        router={router}
        printRef={printRef}
      />
    );
  }

  const g = result.grievance;
  const isPartial = result.status === "partial";

  return (
    <main className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-100 px-5 h-14 flex items-center justify-between sticky top-0 z-50 print:hidden">
        <span className="text-sm font-semibold text-gray-700">शिकायत पर्ची</span>
        {countdown !== null ? (
          <div className="flex items-center gap-2">
            <span className="text-xs font-semibold text-amber-700">Printing in {countdown}s</span>
            <button
              type="button"
              onClick={() => setCountdown(null)}
              className="text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors"
            >
              Cancel
            </button>
          </div>
        ) : (
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
        )}
      </header>

      <div ref={printRef} className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <div className="text-center space-y-2">
          {slug === "varanasi-nagar-nigam" ? (
            <p className="text-lg font-extrabold text-orange-600">वाराणसी नगर निगम</p>
          ) : isJanSunwaiSlug(slug) ? (
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
          <TranscriptSection entries={result.transcript!} isLearning={false} />
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

function LearningResultView({
  slug,
  result,
  router,
  printRef,
}: {
  slug: string;
  result: SessionResultResponse;
  router: ReturnType<typeof useRouter>;
  printRef: React.RefObject<HTMLDivElement>;
}) {
  const lr = result.learning_record;
  const isPartial =
    result.status === "partial" ||
    (result.status === "active" && !lr?.friendly_summary);

  return (
    <main className="min-h-screen bg-gradient-to-b from-pink-50 to-white">
      <header className="bg-white border-b border-gray-100 px-5 h-14 flex items-center justify-between sticky top-0 z-50">
        <span className="text-sm font-semibold text-pink-600">गुड्डी — सीखने का रिकॉर्ड</span>
        <button
          type="button"
          onClick={() => router.push(`/kiosk/${slug}/start`)}
          className="btn-primary text-xs py-2 px-3"
        >
          नया सबक
        </button>
      </header>

      <div ref={printRef} className="max-w-2xl mx-auto px-6 py-8 space-y-6">
        <div className="text-center space-y-2">
          <p className="text-3xl">🌸</p>
          <h1 className="text-xl font-bold text-gray-900">
            {isPartial ? "अधूरा सबक" : "बहुत अच्छे! सबक पूरा हुआ"}
          </h1>
          {lr?.friendly_summary && (
            <p className="text-base text-gray-700 bg-white rounded-xl py-3 px-4 border border-pink-100">
              {lr.friendly_summary}
            </p>
          )}
          {isPartial && (
            <p className="text-sm text-amber-700 bg-amber-50 rounded-lg py-2 px-4">
              बातचीत पूरी नहीं हुई — शिक्षक से मदद लें।
            </p>
          )}
          {isPartial && (
            <button
              type="button"
              className="btn-primary mt-2"
              onClick={() => router.push(`/kiosk/${slug}/start`)}
            >
              फिर से शुरू करें
            </button>
          )}
        </div>

        {lr && (
          <div className="bg-white rounded-2xl border border-pink-100 shadow-sm divide-y divide-gray-100">
            <Section title="बच्चे का नाम" value={lr.learner_name || result.learner_name} />
            <Section title="विषय" value={lr.topic || result.lesson_topic} />
            <Section title="मूड" value={lr.mood_start} />
            <Section title="मोड" value={lr.mode_used} />
            <Section title="रुचि" value={lr.engagement} />
            <Section
              title="शब्द"
              value={
                lr.new_words_clear != null
                  ? `${lr.new_words_clear} साफ, ${lr.emerging_words ?? 0} लगभग`
                  : null
              }
            />
            <Section title="मील का पत्थर" value={lr.milestone_signal} />
            <Section title="ध्यान दें" value={lr.flags !== "none" ? lr.flags : null} />
            <Section
              title="अगली बार"
              value={lr.next_focus?.length ? lr.next_focus.join(", ") : null}
            />
            <Section title="टिप्पणी" value={lr.pronunciation_note} />
          </div>
        )}

        {lr?.words_practiced && lr.words_practiced.length > 0 && (
          <div className="bg-white rounded-2xl border border-pink-100 shadow-sm p-5">
            <h2 className="text-base font-bold text-gray-900 mb-4">शब्द अभ्यास</h2>
            <div className="space-y-2">
              {lr.words_practiced.map((w, i) => (
                <div
                  key={i}
                  className="flex items-center justify-between py-2 border-b border-gray-50 last:border-0"
                >
                  <span className="font-semibold text-gray-800">{w.word}</span>
                  <span className="text-sm text-gray-500">
                    {RESULT_LABEL[w.result] || w.result}
                    {w.said_in_dialect ? " · बोली में" : ""}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {(result.transcript?.length ?? 0) > 0 && (
          <TranscriptSection entries={result.transcript!} isLearning={true} />
        )}

        <div className="text-center text-xs text-gray-400">
          <p>Started: {result.started_at || "—"}</p>
          <p>Ended: {result.ended_at || "—"}</p>
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

function TranscriptSection({
  entries,
  isLearning,
}: {
  entries: KioskTranscriptEntry[];
  isLearning: boolean;
}) {
  const userLabel = isLearning ? "बच्चा" : "आप";
  const agentLabel = isLearning ? "गुड्डी" : "AI सहायक";

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
                  ? isLearning
                    ? "bg-purple-50 border-purple-100"
                    : "bg-amber-50 border-amber-100"
                  : "bg-white border-gray-100 shadow-sm"
              )}
            >
              <p
                className={clsx(
                  "text-xs font-medium mb-1",
                  isUser
                    ? isLearning
                      ? "text-purple-700"
                      : "text-amber-700"
                    : "text-gray-400"
                )}
              >
                {isUser ? userLabel : agentLabel}
              </p>
              <p className="text-gray-800 leading-relaxed">{entry.text}</p>
            </div>
          );
        })}
      </div>
    </div>
  );
}
