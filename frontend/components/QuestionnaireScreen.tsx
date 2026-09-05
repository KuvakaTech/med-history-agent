"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Send, RotateCcw, VolumeX, Volume2, SkipForward } from "lucide-react";
import type { AnswerResponse, ClinicalFlag } from "@/lib/types";
import { api } from "@/lib/api";
import VoiceRecorder from "./VoiceRecorder";
import FlagBadge from "./FlagBadge";
import AIAvatar, { SiriWaveform } from "./AIAvatar";
import {
  SILENCE_RETRY_MESSAGE,
  UNCLEAR_RETRY_MESSAGE,
  useQuestionRetry,
  VOICE_INACTIVITY_MS,
} from "@/hooks/useQuestionRetry";
import clsx from "clsx";

interface Props {
  sessionId: string;
  question: string;
  turnNumber: number;
  flags: ClinicalFlag[];
  language?: string;
  onStreamedAnswer: (resp: AnswerResponse) => void;
  onVoiceAnswer: (resp: AnswerResponse & { transcript: string }) => void;
}

// ─────────────────────────────────────────────
// Sentence-level streaming TTS
// ─────────────────────────────────────────────

// Deepgram TTS has no Hindi voices, so Hindi sessions use the browser's built-in
// speech synthesis (hi-IN voice) instead of the backend /speak endpoint.
function useSentenceTTS(muted: boolean, useBrowserHindi: boolean = false) {
  const [speaking, setSpeaking] = useState(false);
  const queueRef = useRef<Promise<string | null>[]>([]);
  const playIdxRef = useRef(0);
  const playingRef = useRef(false);
  const genRef = useRef(0);
  const sentBufRef = useRef("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopAll = useCallback(() => {
    genRef.current++;
    audioRef.current?.pause();
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
    playingRef.current = false;
  }, []);

  const speakBrowser = useCallback((text: string) => {
    return new Promise<void>((resolve) => {
      if (!("speechSynthesis" in window)) return resolve();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = "hi-IN";
      const hiVoice = window.speechSynthesis
        .getVoices()
        .find((v) => v.lang.toLowerCase().startsWith("hi"));
      if (hiVoice) utterance.voice = hiVoice;
      utterance.onend = () => resolve();
      utterance.onerror = () => resolve();
      window.speechSynthesis.speak(utterance);
    });
  }, []);

  const reset = useCallback(() => {
    stopAll();
    queueRef.current = [];
    playIdxRef.current = 0;
    sentBufRef.current = "";
  }, [stopAll]);

  const playQueue = useCallback(async () => {
    if (playingRef.current) return;
    const gen = genRef.current;
    playingRef.current = true;
    while (playIdxRef.current < queueRef.current.length) {
      // Hindi queue items resolve to the sentence text itself; English items to an audio URL.
      const item = await queueRef.current[playIdxRef.current];
      playIdxRef.current++;
      if (genRef.current !== gen) break;
      if (!item || muted) continue;
      setSpeaking(true);
      if (useBrowserHindi) {
        await speakBrowser(item);
        setSpeaking(false);
      } else {
        await new Promise<void>((resolve) => {
          const audio = new Audio(item);
          audioRef.current = audio;
          audio.onended = () => { setSpeaking(false); resolve(); };
          audio.onerror = () => { setSpeaking(false); resolve(); };
          audio.play().catch(resolve);
        });
      }
      if (genRef.current !== gen) { setSpeaking(false); break; }
    }
    if (genRef.current === gen) playingRef.current = false;
  }, [muted, useBrowserHindi, speakBrowser]);

  const flushSentence = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || muted) return;
    queueRef.current.push(useBrowserHindi ? Promise.resolve(trimmed) : api.speak(trimmed));
    playQueue();
  }, [muted, useBrowserHindi, playQueue]);

  const onToken = useCallback((token: string) => {
    sentBufRef.current += token;
    const match = sentBufRef.current.match(/^([\s\S]*?[.!?।])(\s+|$)/);
    if (match) {
      const sentence = match[1];
      sentBufRef.current = sentBufRef.current.slice(match[0].length);
      flushSentence(sentence);
    }
  }, [flushSentence]);

  const onStreamEnd = useCallback((_fullText: string) => {
    const remainder = sentBufRef.current.trim();
    if (remainder) flushSentence(remainder);
    sentBufRef.current = "";
  }, [flushSentence]);

  const playFull = useCallback((text: string) => {
    if (!text || muted) return;
    reset();
    queueRef.current.push(useBrowserHindi ? Promise.resolve(text) : api.speak(text));
    playQueue();
  }, [muted, useBrowserHindi, reset, playQueue]);

  const replay = useCallback((text: string) => {
    reset();
    playFull(text);
  }, [reset, playFull]);

  return { speaking, onToken, onStreamEnd, playFull, replay, reset, stopAll };
}

// ─────────────────────────────────────────────
// Main screen
// ─────────────────────────────────────────────

export default function QuestionnaireScreen({
  sessionId, question, turnNumber, flags, language,
  onStreamedAnswer, onVoiceAnswer,
}: Props) {
  const [textAnswer, setTextAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [streamingQuestion, setStreamingQuestion] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const [voiceStage, setVoiceStage] = useState<"idle" | "connecting" | "recording" | "transcribing" | "thinking" | "error">("idle");
  const abortRef = useRef<(() => void) | null>(null);
  const autoSkippingRef = useRef(false);

  const tts = useSentenceTTS(muted);
  const skipNextTTSRef = useRef(false);
  const submitTextRef = useRef<(answer: string) => void>(() => {});

  const { retryMessage, autoSkipNotice, handleFailure, handleSuccess } = useQuestionRetry(
    question,
    () => {
      autoSkippingRef.current = true;
      submitTextRef.current("I'd prefer to skip this question.");
    },
    (text) => tts.replay(text),
  );

  useEffect(() => {
    if (streamingQuestion !== null) return;
    if (skipNextTTSRef.current) { skipNextTTSRef.current = false; return; }
    tts.reset();
    if (question) tts.playFull(question);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question]);

  const displayQuestion = streamingQuestion !== null ? streamingQuestion : question;
  const recentFlags = flags.slice(-3);

  const submitText = useCallback(async (answer: string) => {
    if (!answer.trim() || submitting) return;
    setError("");
    setSubmitting(true);
    tts.reset();
    setStreamingQuestion("");

    let accumulated = "";
    const abort = api.submitAnswerStream(
      sessionId, answer.trim(),
      (token) => {
        accumulated += token;
        setStreamingQuestion(accumulated);
        tts.onToken(token);
      },
      (data) => {
        if (data.retry_same_question) {
          setStreamingQuestion(null);
          setSubmitting(false);
          if (!autoSkippingRef.current) {
            handleFailure(data.retry_message ?? UNCLEAR_RETRY_MESSAGE);
          } else {
            autoSkippingRef.current = false;
          }
          return;
        }
        handleSuccess();
        autoSkippingRef.current = false;
        if (data.history_complete) {
          tts.stopAll();
        } else {
          tts.onStreamEnd(accumulated);
          skipNextTTSRef.current = true;
        }
        setStreamingQuestion(null);
        setSubmitting(false);
        setTextAnswer("");
        onStreamedAnswer({
          next_question: data.next_question,
          history_complete: data.history_complete,
          new_flags: (data.new_flags ?? []) as AnswerResponse["new_flags"],
        });
      },
      (msg) => {
        console.error("submitAnswerStream failed:", msg);
        setError("Something went wrong. Please try again.");
        setSubmitting(false);
        setStreamingQuestion(null);
      },
      (message) => {
        setStreamingQuestion(null);
        setSubmitting(false);
        if (!autoSkippingRef.current) {
          handleFailure(message);
        } else {
          autoSkippingRef.current = false;
        }
      },
    );
    abortRef.current = abort;
  }, [submitting, sessionId, tts, onStreamedAnswer, handleFailure, handleSuccess]);

  submitTextRef.current = submitText;

  const skipQuestion = useCallback(() => {
    autoSkippingRef.current = false;
    submitText("I'd prefer to skip this question.");
  }, [submitText]);

  const handleVoiceAnswer = useCallback((resp: AnswerResponse & { transcript: string }) => {
    handleSuccess();
    autoSkippingRef.current = false;
    if (resp.history_complete) tts.stopAll();
    else skipNextTTSRef.current = true;
    onVoiceAnswer(resp);
  }, [tts, onVoiceAnswer, handleSuccess]);

  const handleVoiceRetry = useCallback((message: string) => {
    setSubmitting(false);
    handleFailure(message);
  }, [handleFailure]);

  const handleVoiceToken = useCallback((token: string) => { tts.onToken(token); }, [tts]);

  const handleVoiceStreamEnd = useCallback((fullText: string, historyComplete: boolean) => {
    if (!historyComplete) tts.onStreamEnd(fullText);
    else tts.stopAll();
  }, [tts]);

  useEffect(() => {
    if (voiceStage !== "idle" || submitting || tts.speaking || !question) return;
    const timer = setTimeout(() => {
      handleFailure(SILENCE_RETRY_MESSAGE);
    }, VOICE_INACTIVITY_MS);
    return () => clearTimeout(timer);
  }, [voiceStage, submitting, tts.speaking, question, handleFailure]);

  useEffect(() => () => { abortRef.current?.(); }, []);

  return (
    <div className="space-y-5 fade-up">
      {/* AI Avatar */}
      <div className="flex flex-col items-center gap-3 pt-2 pb-4">
        <AIAvatar speaking={tts.speaking} loading={submitting} size="lg" />
        <SiriWaveform active={tts.speaking} />

        <div className="flex items-center gap-2">
          <button
            onClick={() => setMuted((m) => { if (!m) tts.stopAll(); return !m; })}
            className="p-2 rounded-lg bg-white border border-gray-200 text-gray-400 hover:text-brand hover:border-brand/30 transition-all shadow-sm"
          >
            {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
          </button>
          <button
            onClick={() => tts.replay(question)}
            className="p-2 rounded-lg bg-white border border-gray-200 text-gray-400 hover:text-brand hover:border-brand/30 transition-all shadow-sm"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs font-semibold text-gray-400 uppercase tracking-widest">
          {submitting ? "AI is thinking…" : tts.speaking ? "Speaking" : `Question ${turnNumber}`}
        </p>
      </div>

      {/* Question bubble */}
      <div className={clsx(
        "relative rounded-3xl p-6 transition-all duration-300",
        tts.speaking
          ? "bg-brand-light border-2 border-brand/30 shadow-md shadow-brand/10"
          : "bg-white border border-gray-200 shadow-sm"
      )}>
        <div
          className="absolute -top-3 left-6 w-6 h-6 rotate-45 rounded-sm"
          style={{
            background: tts.speaking ? "#f0eaff" : "white",
            borderLeft: tts.speaking ? "2px solid rgba(51,4,159,0.2)" : "1px solid #e5e7eb",
            borderTop:  tts.speaking ? "2px solid rgba(51,4,159,0.2)" : "1px solid #e5e7eb",
          }}
        />
        {submitting && streamingQuestion === "" ? (
          <div className="flex items-center gap-3 text-brand">
            <svg className="animate-spin h-5 w-5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="font-medium">Thinking…</span>
          </div>
        ) : (
          <p className="text-lg font-semibold text-gray-800 leading-relaxed">
            {displayQuestion}
            {streamingQuestion !== null && submitting && (
              <span className="inline-block w-0.5 h-5 bg-brand ml-0.5 animate-pulse align-text-bottom" />
            )}
          </p>
        )}
      </div>

      {/* Voice answer */}
      <div className="bg-white border border-gray-100 rounded-xl p-5 space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-gray-700">
          <span className="w-7 h-7 rounded-lg bg-brand-light text-brand flex items-center justify-center text-base">🎤</span>
          <span>Speak your answer</span>
          <span className="text-xs text-gray-400 font-normal">— transcribed &amp; analysed instantly</span>
        </div>
        <VoiceRecorder
          sessionId={sessionId}
          onAnswer={handleVoiceAnswer}
          onToken={handleVoiceToken}
          onStreamEnd={(text, done) => handleVoiceStreamEnd(text, done)}
          onRecordingStart={() => setVoiceStage("recording")}
          onStageChange={setVoiceStage}
          onRetry={handleVoiceRetry}
          disabled={submitting || tts.speaking}
        />
      </div>

      {/* Divider */}
      <div className="flex items-center gap-3">
        <div className="flex-1 border-t border-gray-200" />
        <span className="text-xs text-gray-400 font-medium bg-gray-50 px-2">or type</span>
        <div className="flex-1 border-t border-gray-200" />
      </div>

      {/* Text answer */}
      <div className="flex gap-3 items-start">
        <textarea
          className="input-field flex-1 resize-none"
          rows={3}
          placeholder="Type your answer here…"
          value={textAnswer}
          onChange={(e) => setTextAnswer(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submitText(textAnswer); }}
          disabled={submitting}
        />
        <button
          className={clsx(
            "self-end px-4 py-3 rounded-lg font-semibold transition-all duration-150 shadow-sm",
            textAnswer.trim() && !submitting
              ? "bg-brand hover:bg-brand-dark text-white active:scale-95"
              : "bg-gray-100 text-gray-300 cursor-not-allowed"
          )}
          onClick={() => submitText(textAnswer)}
          disabled={submitting || !textAnswer.trim()}
        >
          <Send className="w-4 h-4" />
        </button>
      </div>

      <div className="flex items-center justify-between -mt-2">
        <p className="text-xs text-gray-400">⌘ + Enter to submit</p>
        <button
          onClick={skipQuestion}
          disabled={submitting}
          className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-gray-600 disabled:opacity-40 transition-colors"
        >
          <SkipForward className="w-3.5 h-3.5" />
          Skip question
        </button>
      </div>

      {recentFlags.length > 0 && (
        <div className="space-y-2">
          {recentFlags.map((f, i) => <FlagBadge key={i} flag={f} />)}
        </div>
      )}

      {autoSkipNotice && (
        <div className="bg-gray-50 border border-gray-200 text-gray-600 rounded-lg px-4 py-3 text-sm font-medium">
          Skipping this question…
        </div>
      )}

      {retryMessage && !autoSkipNotice && (
        <div className="bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-4 py-3 text-sm font-medium">
          {retryMessage}
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm font-medium">
          {error}
        </div>
      )}
    </div>
  );
}
