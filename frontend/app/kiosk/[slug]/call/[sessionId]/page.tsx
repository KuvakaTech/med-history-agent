"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { KioskVoiceWS, kioskApi } from "@/lib/kiosk-api";
import type { KioskWSEvent } from "@/lib/kiosk-types";
import clsx from "clsx";

type Phase = "connecting" | "complaint" | "processing" | "done" | "error";

export default function KioskCallPage() {
  const params = useParams();
  const router = useRouter();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;

  const wsRef = useRef<KioskVoiceWS | null>(null);
  const fatalErrorRef = useRef(false);

  const [phase, setPhase] = useState<Phase>("connecting");
  const [currentQuestion, setCurrentQuestion] = useState("");
  const [partialTranscript, setPartialTranscript] = useState("");
  const [agentSpeaking, setAgentSpeaking] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const handleEvent = useCallback(
    (event: KioskWSEvent) => {
      switch (event.type) {
        case "ready":
        case "complaint_started":
          setPhase("complaint");
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
        case "result_ready":
          router.push(`/kiosk/${slug}/result/${sessionId}`);
          break;
        case "session_partial":
          setPhase("processing");
          setTimeout(() => router.push(`/kiosk/${slug}/result/${sessionId}`), 1500);
          break;
        case "ended":
          if (!fatalErrorRef.current) {
            router.push(`/kiosk/${slug}/result/${sessionId}`);
          }
          break;
        case "error":
          if (event.fatal) {
            fatalErrorRef.current = true;
            setPhase("error");
            setErrorMsg(event.message || "कुछ गलत हो गया।");
          }
          break;
      }
    },
    [slug, sessionId, router]
  );

  useEffect(() => {
    const ws = new KioskVoiceWS({
      onEvent: handleEvent,
      onMicOpen: () => setPartialTranscript(""),
    });
    wsRef.current = ws;

    ws.connect(kioskApi.voiceWsUrl(slug, sessionId)).catch((err) => {
      setPhase("error");
      setErrorMsg(err.message || "कनेक्शन विफल।");
    });

    return () => ws.stop();
  }, [slug, sessionId, handleEvent]);

  const handleStop = () => {
    wsRef.current?.stop();
    router.push(`/kiosk/${slug}/result/${sessionId}`);
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

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col">
      <header className="bg-white border-b border-gray-100 px-4 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-amber-800">Jan Sunwai</span>
          <span className="text-xs text-gray-400">
            {phase === "processing" ? "प्रसंस्करण…" : "शिकायत दर्ज"}
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

      <div className="flex-1 flex flex-col items-center justify-center px-6 py-10 gap-8">
        <div
          className={clsx(
            "w-32 h-32 rounded-full flex items-center justify-center transition-all",
            agentSpeaking
              ? "bg-amber-400 shadow-lg shadow-amber-200 scale-105"
              : "bg-amber-100"
          )}
        >
          <span className="text-4xl">🎙️</span>
        </div>

        <p className="text-sm text-gray-500">
          {phase === "connecting"
            ? "कनेक्ट हो रहा है…"
            : agentSpeaking
              ? "AI सहायक बोल रही है…"
              : "आप बोल सकते हैं — माइक चालू है"}
        </p>

        {currentQuestion && (
          <div className="max-w-lg w-full bg-white rounded-2xl border border-gray-100 p-5 shadow-sm">
            <p className="text-xs text-gray-400 mb-2">AI सहायक</p>
            <p className="text-gray-800 leading-relaxed">{currentQuestion}</p>
          </div>
        )}

        {partialTranscript && (
          <div className="max-w-lg w-full bg-amber-50 rounded-2xl border border-amber-100 p-4">
            <p className="text-xs text-amber-700 mb-1">आप</p>
            <p className="text-gray-700">{partialTranscript}</p>
          </div>
        )}

        {phase === "processing" && (
          <p className="text-sm text-gray-500 animate-pulse">शिकायत दर्ज की जा रही है…</p>
        )}
      </div>
    </main>
  );
}
