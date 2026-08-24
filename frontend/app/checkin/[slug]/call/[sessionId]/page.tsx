"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { TicketVoiceWS, ticketApi } from "@/lib/ticketing-api";
import type { TicketCategory, TicketFlag, TicketWSEvent } from "@/lib/ticketing-types";
import clsx from "clsx";

// ── State machine ─────────────────────────────────────────────
type Phase = "connecting" | "triage" | "category_select" | "consultation" | "processing" | "done" | "error";

interface CallState {
  phase: Phase;
  currentQuestion: string;
  partialTranscript: string;
  agentSpeaking: boolean;
  micOpen: boolean;
  flags: TicketFlag[];
  availableCategories: TicketCategory[];
  confirmedCategory: TicketCategory | null;
  errorMsg: string;
  turn: number;
  stillThereNudge: boolean;
}

export default function CallPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const slug = params.slug as string;
  const sessionId = params.sessionId as string;
  const language = searchParams.get("lang") || "hi";

  const wsRef = useRef<TicketVoiceWS | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const audioQueueRef = useRef<Array<{ question: string; b64: string | null }>>([]);
  const playingRef = useRef(false);
  const onMicOpenCallbackRef = useRef<(() => void) | null>(null);

  const [state, setState] = useState<CallState>({
    phase: "connecting",
    currentQuestion: "",
    partialTranscript: "",
    agentSpeaking: false,
    micOpen: false,
    flags: [],
    availableCategories: [],
    confirmedCategory: null,
    errorMsg: "",
    turn: 0,
    stillThereNudge: false,
  });

  const updateState = useCallback((patch: Partial<CallState>) => {
    setState((prev) => ({ ...prev, ...patch }));
  }, []);

  // ── Audio playback queue ──────────────────────────────────
  const playNext = useCallback(() => {
    if (playingRef.current || audioQueueRef.current.length === 0) return;
    const item = audioQueueRef.current.shift()!;
    playingRef.current = true;
    updateState({ agentSpeaking: true, currentQuestion: item.question });

    if (!item.b64) {
      playingRef.current = false;
      updateState({ agentSpeaking: false });
      onMicOpenCallbackRef.current?.();
      return;
    }

    try {
      const binary = atob(item.b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
      const blob = new Blob([bytes], { type: "audio/mpeg" });
      const url = URL.createObjectURL(blob);

      const audio = new Audio(url);
      audioRef.current = audio;
      audio.onended = () => {
        URL.revokeObjectURL(url);
        playingRef.current = false;
        updateState({ agentSpeaking: false });
        if (audioQueueRef.current.length > 0) playNext();
      };
      audio.onerror = () => {
        URL.revokeObjectURL(url);
        playingRef.current = false;
        updateState({ agentSpeaking: false });
        onMicOpenCallbackRef.current?.();
      };
      audio.play().catch(() => {
        playingRef.current = false;
        updateState({ agentSpeaking: false });
        onMicOpenCallbackRef.current?.();
      });
    } catch {
      playingRef.current = false;
      updateState({ agentSpeaking: false });
      onMicOpenCallbackRef.current?.();
    }
  }, [updateState]);

  const enqueueAudio = useCallback(
    (question: string, b64: string | null) => {
      audioQueueRef.current.push({ question, b64 });
      playNext();
    },
    [playNext]
  );

  // ── WS event handler ──────────────────────────────────────
  const handleEvent = useCallback(
    (event: TicketWSEvent) => {
      switch (event.type) {
        case "ready":
        case "triage_started":
          updateState({ phase: "triage" });
          break;

        case "category_identified":
          updateState({ confirmedCategory: event.category });
          break;

        case "category_manual_required":
          updateState({
            phase: "category_select",
            availableCategories: event.categories,
            micOpen: false,
            partialTranscript: "",
            stillThereNudge: false,
          });
          break;

        case "category_confirmed":
          updateState({
            confirmedCategory: { key: event.category.key, label: event.category.label },
          });
          break;

        case "consultation_started":
          updateState({ phase: "consultation" });
          break;

        case "red_flag_raised":
          setState((prev) => ({
            ...prev,
            flags: [
              ...prev.flags,
              {
                flag_type: event.flag.flag_type as TicketFlag["flag_type"],
                description: event.flag.description,
              },
            ],
          }));
          break;

        case "consultation_ended":
          updateState({ phase: "processing" });
          break;

        case "result_ready":
          router.push(`/checkin/${slug}/result/${sessionId}`);
          break;

        case "session_partial":
          updateState({ phase: "processing" });
          setTimeout(() => router.push(`/checkin/${slug}/result/${sessionId}`), 1500);
          break;

        case "partial_transcript":
          updateState({ partialTranscript: event.text, stillThereNudge: false });
          break;

        case "silence_nudge":
          updateState({ stillThereNudge: true });
          break;

        case "ended":
          router.push(`/checkin/${slug}/result/${sessionId}`);
          break;

        case "error":
          if (event.fatal) updateState({ phase: "error", errorMsg: event.message });
          break;
      }
    },
    [slug, sessionId, router, updateState]
  );

  // ── Connect on mount ──────────────────────────────────────
  useEffect(() => {
    const ws = new TicketVoiceWS({
      onEvent: handleEvent,
      onAudio: enqueueAudio,
      onMicOpen: () => updateState({ micOpen: true, partialTranscript: "", stillThereNudge: false }),
    });
    wsRef.current = ws;
    onMicOpenCallbackRef.current = () => updateState({ micOpen: true, partialTranscript: "", stillThereNudge: false });

    ws.connect(ticketApi.voiceWsUrl(slug, sessionId)).catch((err) => {
      updateState({ phase: "error", errorMsg: err.message || "Connection failed." });
    });

    return () => {
      ws.stop();
      audioRef.current?.pause();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCategorySelect = (cat: TicketCategory) => {
    wsRef.current?.sendCategorySelected(cat.key, cat.label);
    updateState({ confirmedCategory: cat, phase: "consultation", availableCategories: [] });
  };

  const handleStop = () => {
    wsRef.current?.stop();
    router.push(`/checkin/${slug}/result/${sessionId}`);
  };

  const criticalFlags = state.flags.filter((f) => f.flag_type === "CRITICAL_RED_FLAG");

  return (
    <main className="min-h-screen bg-gray-50 flex flex-col">
      {/* Header */}
      <header className="bg-white border-b border-gray-100 px-4 h-14 flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-2">
          <img src="/kuvaka_logo.png" alt="Kuvaka" className="h-5 w-auto" />
          <PhaseLabel phase={state.phase} />
        </div>
        <div className="flex items-center gap-2">
          {state.confirmedCategory && (
            <span className="hidden sm:flex px-2 py-1 bg-brand-light text-brand text-xs font-semibold rounded-full">
              {state.confirmedCategory.label}
            </span>
          )}
          <button
            onClick={handleStop}
            className="text-xs text-gray-400 hover:text-gray-600 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors"
          >
            End Call
          </button>
        </div>
      </header>

      {criticalFlags.length > 0 && (
        <div className="bg-red-600 text-white text-xs font-semibold text-center py-2.5 px-4">
          🚨 Critical alert — inform staff immediately
        </div>
      )}

      <div className="flex-1 flex flex-col items-center px-4 py-8 gap-6">
        <div className="w-full max-w-sm space-y-6 fade-up">

          {(state.phase === "connecting" || state.phase === "processing") && (
            <div className="text-center space-y-4 py-12">
              <OrbAnimation speaking={false} listening={false} />
              <p className="text-sm text-gray-500">
                {state.phase === "processing" ? "Preparing your summary…" : "Connecting…"}
              </p>
            </div>
          )}

          {state.phase === "error" && (
            <div className="card text-center space-y-4 py-8">
              <div className="text-4xl">😕</div>
              <p className="text-gray-600 text-sm">{state.errorMsg}</p>
              <button onClick={() => router.push(`/checkin/${slug}/start`)} className="btn-primary">
                Try Again
              </button>
            </div>
          )}

          {(state.phase === "triage" ||
            state.phase === "consultation" ||
            state.phase === "category_select") && (
            <>
              <div className="flex flex-col items-center gap-3">
                <OrbAnimation
                  speaking={state.agentSpeaking}
                  listening={state.micOpen && !state.agentSpeaking}
                />
                <p
                  className={clsx(
                    "text-xs font-semibold uppercase tracking-widest",
                    state.agentSpeaking
                      ? "text-brand"
                      : state.micOpen
                      ? "text-green-600"
                      : "text-gray-400"
                  )}
                >
                  {state.agentSpeaking ? "Speaking…" : state.micOpen ? "Listening…" : "Please wait"}
                </p>
              </div>

              {state.currentQuestion && (
                <div
                  className={clsx(
                    "relative rounded-3xl p-5 transition-all duration-300",
                    state.agentSpeaking
                      ? "bg-brand-light border-2 border-brand/30 shadow-md shadow-brand/10"
                      : "bg-white border border-gray-200 shadow-sm"
                  )}
                >
                  <div
                    className="absolute -top-2.5 left-5 w-5 h-5 rotate-45 rounded-sm"
                    style={{
                      background: state.agentSpeaking ? "#f0eaff" : "white",
                      borderLeft: state.agentSpeaking
                        ? "2px solid rgba(51,4,159,0.2)"
                        : "1px solid #e5e7eb",
                      borderTop: state.agentSpeaking
                        ? "2px solid rgba(51,4,159,0.2)"
                        : "1px solid #e5e7eb",
                    }}
                  />
                  <p className="text-base font-semibold text-gray-800 leading-relaxed">
                    {state.currentQuestion}
                  </p>
                </div>
              )}

              {state.stillThereNudge && state.micOpen && !state.agentSpeaking && (
                <div className="bg-amber-50 border border-amber-200 rounded-2xl px-4 py-3 text-center">
                  <p className="text-sm text-amber-700 font-medium">
                    Still there? We can&apos;t hear you — please speak, or check your microphone.
                  </p>
                </div>
              )}

              {state.partialTranscript && state.micOpen && (
                <div className="bg-white border border-gray-100 rounded-2xl px-4 py-3 shadow-sm">
                  <p className="text-xs text-gray-400 mb-1">You said:</p>
                  <p className="text-sm text-gray-700 italic">{state.partialTranscript}</p>
                </div>
              )}

              {state.micOpen && !state.agentSpeaking && (
                <div className="flex items-center justify-center gap-2 text-green-600">
                  <span className="relative flex h-2.5 w-2.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-green-500" />
                  </span>
                  <span className="text-xs font-semibold">Microphone active — speak now</span>
                </div>
              )}

              {state.phase === "category_select" && state.availableCategories.length > 0 && (
                <div className="card space-y-3 border-brand/30 border">
                  <p className="text-sm font-semibold text-gray-700">Please select your department:</p>
                  <div className="grid grid-cols-1 gap-2 max-h-60 overflow-y-auto">
                    {state.availableCategories.map((cat) => (
                      <button
                        key={cat.key}
                        onClick={() => handleCategorySelect(cat)}
                        className="text-left px-4 py-3 rounded-lg border border-gray-200 hover:border-brand hover:bg-brand-light text-sm font-medium text-gray-700 hover:text-brand transition-all"
                      >
                        {cat.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {state.flags.length > 0 && (
                <div className="space-y-1.5">
                  {state.flags.slice(-2).map((f, i) => (
                    <div
                      key={i}
                      className={clsx(
                        "text-xs px-3 py-2 rounded-lg",
                        f.flag_type === "CRITICAL_RED_FLAG"
                          ? "bg-red-50 text-red-700 border border-red-200"
                          : f.flag_type === "RED_FLAG"
                          ? "bg-amber-50 text-amber-700 border border-amber-200"
                          : "bg-sky-50 text-sky-700 border border-sky-200"
                      )}
                    >
                      {f.description}
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </main>
  );
}

function PhaseLabel({ phase }: { phase: Phase }) {
  const labels: Record<Phase, string> = {
    connecting: "Connecting",
    triage: "Intake",
    category_select: "Select Department",
    consultation: "Check-In",
    processing: "Processing",
    done: "Complete",
    error: "Error",
  };
  return <span className="text-xs text-gray-400">{labels[phase]}</span>;
}

function OrbAnimation({ speaking, listening }: { speaking: boolean; listening: boolean }) {
  return (
    <div className="relative flex items-center justify-center w-28 h-28">
      {speaking && (
        <>
          <div className="absolute inset-0 rounded-full bg-brand/10 ring-1" />
          <div className="absolute inset-0 rounded-full bg-brand/8 ring-2" />
        </>
      )}
      {listening && (
        <div className="absolute inset-0 rounded-full border-2 border-green-400 animate-ping opacity-30" />
      )}
      <div
        className={clsx(
          "w-20 h-20 rounded-full flex items-center justify-center shadow-lg transition-all duration-300",
          speaking
            ? "bg-brand orb-speak shadow-brand/40"
            : listening
            ? "bg-green-500 orb-breathe shadow-green-500/30"
            : "bg-brand-muted orb-breathe shadow-brand/20"
        )}
      >
        {speaking ? (
          <SiriWaveform active />
        ) : listening ? (
          <span className="text-white text-2xl">🎤</span>
        ) : (
          <span className="text-brand text-2xl">🤖</span>
        )}
      </div>
    </div>
  );
}

function SiriWaveform({ active }: { active: boolean }) {
  return (
    <div className={clsx("flex items-center gap-[3px]", !active && "opacity-40")}>
      {[1, 2, 3, 4, 5].map((i) => (
        <div key={i} className={`w-[3px] rounded-full bg-white bar-${i}`} />
      ))}
    </div>
  );
}
