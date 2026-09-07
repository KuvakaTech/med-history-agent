"use client";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { KioskVoiceWS, kioskApi } from "@/lib/kiosk-api";
import type { CentreResponse, KioskWSEvent } from "@/lib/kiosk-types";
import { isBarwaniJanSunwaiSlug, isJanSunwaiSlug, isLearningSlug } from "@/lib/kiosk-types";
import clsx from "clsx";

type Phase = "connecting" | "active" | "processing" | "done" | "error";

type ActiveCard = {
  wordId: string;
  hindi: string;
  imageUrl: string;
  mode: "teach" | "quiz";
};

type AnswerFeedback = {
  result: "clear" | "close" | "wrong";
  expectedHindi: string;
};

export default function KioskCallPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;

  const wsRef = useRef<KioskVoiceWS | null>(null);
  const fatalErrorRef = useRef(false);
  const navigatedRef = useRef(false);
  const handlerRef = useRef<(event: KioskWSEvent) => void>(() => {});

  const [phase, setPhase] = useState<Phase>("connecting");
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");
  const [centre, setCentre] = useState<CentreResponse | null>(null);
  const [activeCard, setActiveCard] = useState<ActiveCard | null>(null);
  const [answerFeedback, setAnswerFeedback] = useState<AnswerFeedback | null>(null);
  const feedbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const isLearning = isLearningSlug(slug) || centre?.centre_kind === "learning";
  const agentLabel = isLearning ? "गुड्डी" : "AI सहायक";
  const userLabel = isLearning ? "बच्चा" : "आप";
  const sessionLabel = isLearning ? "हिंदी सीखना" : "शिकायत दर्ज";
  const processingLabel = isLearning
    ? "सीखने का रिकॉर्ड बन रहा है…"
    : "शिकायत दर्ज की जा रही है…";
  const resultQuery = isLearning ? "" : "?autoprint=1";

  const goToResult = () => {
    if (navigatedRef.current) return;
    navigatedRef.current = true;
    router.push(`/kiosk/${slug}/result/${sessionId}${resultQuery}`);
  };

  handlerRef.current = (event: KioskWSEvent) => {
    switch (event.type) {
      case "ready":
      case "complaint_started":
      case "lesson_started":
        setPhase("active");
        break;
      case "agent_speaking":
        setCurrentQuestion(event.question || "");
        setAgentSpeaking(true);
        break;
      case "agent_audio_chunk":
        setAgentSpeaking(true);
        break;
      case "agent_done_speaking":
      case "interrupt":
        setAgentSpeaking(false);
        break;
      case "partial_transcript":
        setPartialTranscript(event.text || "");
        break;
      case "show_word_card":
        setActiveCard({
          wordId: event.word_id || "",
          hindi: event.hindi || "",
          imageUrl: event.image_url || "",
          mode: (event.mode as ActiveCard["mode"]) || "teach",
        });
        break;
      case "word_answer_result":
        if (event.result && event.expected_hindi) {
          setAnswerFeedback({
            result: event.result,
            expectedHindi: event.expected_hindi,
          });
          if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
          feedbackTimerRef.current = setTimeout(() => setAnswerFeedback(null), 3000);
        }
        break;
      case "result_ready":
        goToResult();
        break;
      case "session_partial":
        setPhase("processing");
        setTimeout(() => goToResult(), 1500);
        break;
      case "error":
        if (event.fatal) {
          fatalErrorRef.current = true;
          setPhase("error");
          setErrorMsg(event.message || "कुछ गलत हो गया।");
        }
        break;
    }
  };

  useEffect(() => {
    kioskApi.getCentre(slug).then(setCentre).catch(() => null);
  }, [slug]);

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

  useEffect(() => {
    fatalErrorRef.current = false;
    navigatedRef.current = false;

    let alive = true;
    const ws = new KioskVoiceWS({
      onEvent: (event) => {
        if (!alive) return;
        handlerRef.current(event);
      },
      onMicOpen: () => setPartialTranscript(""),
    });
    wsRef.current = ws;

    ws.connect(kioskApi.voiceWsUrl(slug, sessionId)).catch((err) => {
      if (!alive) return;
      setPhase("error");
      setErrorMsg(err.message || "कनेक्शन विफल।");
    });

    return () => {
      alive = false;
      ws.stop();
      wsRef.current = null;
    };
  }, [slug, sessionId]);

  useEffect(() => {
    return () => {
      if (feedbackTimerRef.current) clearTimeout(feedbackTimerRef.current);
    };
  }, []);

  const handleStop = () => {
    wsRef.current?.stop();
    goToResult();
  };

  if (phase === "error") {
    return (
      <main className="min-h-screen flex flex-col items-center justify-center px-6 bg-gray-50">
        <p className="text-red-600 font-medium mb-4">{errorMsg}</p>
        <button
          type="button"
          className="btn-primary"
          onClick={() => router.push(`/kiosk/${slug}/start`)}
        >
          फिर से शुरू करें
        </button>
      </main>
    );
  }

  const accent = isLearning
    ? agentSpeaking
      ? "bg-pink-400 shadow-lg shadow-pink-200"
      : "bg-pink-100"
    : agentSpeaking
      ? "bg-amber-400 shadow-lg shadow-amber-200"
      : "bg-amber-100";

  return (
    <main
      className={clsx(
        "min-h-screen flex flex-col",
        isLearning ? "bg-gradient-to-b from-pink-50 to-white" : "bg-gray-50"
      )}
    >
      <header className="bg-white border-b border-gray-100 px-4 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-2">
          {slug === "barwani-guddi" ? (
            <span className="text-sm font-extrabold text-pink-600">गुड्डी 🌸</span>
          ) : slug === "varanasi-nagar-nigam" ? (
            <span className="text-sm font-extrabold text-orange-600">वाराणसी नगर निगम</span>
          ) : isJanSunwaiSlug(slug) ? (
            <span className="text-sm font-extrabold text-orange-600">वाराणसी जन सुनवाई</span>
          ) : isBarwaniJanSunwaiSlug(slug) ? (
            <span className="text-sm font-extrabold text-orange-600">बड़वानी जन सुनवाई</span>
          ) : (
            <span className="text-sm font-semibold text-amber-800">
              {centre?.name || "शिकायत कियोस्क"}
            </span>
          )}
          <span className="text-xs text-gray-400">
            {phase === "processing" ? "प्रसंस्करण…" : sessionLabel}
          </span>
        </div>
        <button
          type="button"
          onClick={handleStop}
          className="text-xs text-white font-semibold px-3 py-1.5 rounded-lg bg-red-600 hover:bg-red-700"
        >
          समाप्त करें
        </button>
      </header>

      <div className="flex-1 flex flex-col items-center justify-center px-6 py-10 gap-6">
        {isLearning && activeCard && (
          <WordCard card={activeCard} feedback={answerFeedback} />
        )}

        <div
          className={clsx(
            "rounded-full flex items-center justify-center transition-all scale-100",
            activeCard && isLearning ? "w-20 h-20" : "w-32 h-32",
            accent,
            agentSpeaking && "scale-105"
          )}
        >
          <span className={clsx(activeCard && isLearning ? "text-2xl" : "text-4xl")}>
            {isLearning ? "🌸" : "🎙️"}
          </span>
        </div>

        <p className="text-sm text-gray-500">
          {phase === "connecting"
            ? "कनेक्ट हो रहा है…"
            : agentSpeaking
              ? `${agentLabel} बोल रही है…`
              : `${userLabel} बोल सकते हैं — माइक चालू है`}
        </p>

        {currentQuestion && (
          <div className="max-w-lg w-full bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
            <p className="text-xs text-gray-400 mb-2">{agentLabel}</p>
            <p className="text-gray-800 leading-relaxed">{currentQuestion}</p>
          </div>
        )}

        {partialTranscript && (
          <div
            className={clsx(
              "max-w-lg w-full rounded-2xl border p-4",
              isLearning
                ? "bg-purple-50 border-purple-100"
                : "bg-amber-50 border-amber-100"
            )}
          >
            <p
              className={clsx(
                "text-xs mb-1",
                isLearning ? "text-purple-700" : "text-amber-700"
              )}
            >
              {userLabel}
            </p>
            <p className="text-gray-700">{partialTranscript}</p>
          </div>
        )}

        {phase === "processing" && (
          <p className="text-sm text-gray-500 animate-pulse">{processingLabel}</p>
        )}
      </div>
    </main>
  );
}

function WordCard({
  card,
  feedback,
}: {
  card: ActiveCard;
  feedback: AnswerFeedback | null;
}) {
  return (
    <div className="max-w-sm w-full bg-white rounded-3xl border-2 border-pink-200 shadow-md p-4 space-y-3">
      <div className="relative aspect-square w-full rounded-2xl overflow-hidden bg-pink-50">
        {card.imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={card.imageUrl}
            alt={card.hindi}
            className="w-full h-full object-contain p-4"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-6xl">📷</div>
        )}
      </div>
      <p className="text-center text-xl font-bold text-pink-700">{card.hindi}</p>
      {card.mode === "quiz" && !feedback && (
        <p className="text-center text-sm text-gray-500">यह क्या है? बोलो!</p>
      )}
      {feedback && (
        <p
          className={clsx(
            "text-center text-sm font-medium rounded-xl py-2 px-3",
            feedback.result === "clear" && "bg-green-50 text-green-700",
            feedback.result === "close" && "bg-amber-50 text-amber-700",
            feedback.result === "wrong" && "bg-pink-50 text-pink-700"
          )}
        >
          {feedback.result === "clear"
            ? "बहुत अच्छे! ✅"
            : feedback.result === "close"
              ? `लगभग सही! साथ में बोलो — ${feedback.expectedHindi}`
              : `यह ${feedback.expectedHindi} है — एक बार साथ में बोलो`}
        </p>
      )}
    </div>
  );
}
