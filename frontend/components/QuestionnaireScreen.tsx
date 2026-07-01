"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Send, RotateCcw, VolumeX, Volume2, SkipForward } from "lucide-react";
import type { AnswerResponse, ClinicalFlag } from "@/lib/types";
import { api } from "@/lib/api";
import VoiceRecorder from "./VoiceRecorder";
import FlagBadge from "./FlagBadge";
import AIAvatar, { SiriWaveform } from "./AIAvatar";
import clsx from "clsx";

interface Props {
  sessionId: string;
  question: string;
  turnNumber: number;
  flags: ClinicalFlag[];
  onStreamedAnswer: (resp: AnswerResponse) => void;
  onVoiceAnswer: (resp: AnswerResponse & { transcript: string }) => void;
}

// ─────────────────────────────────────────────
// Sentence-level streaming TTS
// Fires a TTS request as soon as each sentence is complete,
// plays them in order while pre-fetching the next one.
// ─────────────────────────────────────────────

function useSentenceTTS(muted: boolean) {
  const [speaking, setSpeaking] = useState(false);
  const queueRef = useRef<Promise<string | null>[]>([]);  // TTS URL promises
  const playIdxRef = useRef(0);
  const playingRef = useRef(false);
  const genRef = useRef(0);   // incremented on every stop/reset to invalidate in-flight plays
  const sentBufRef = useRef("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const stopAll = useCallback(() => {
    genRef.current++;           // invalidate any in-flight playQueue invocation
    audioRef.current?.pause();
    setSpeaking(false);
    playingRef.current = false;
  }, []);

  const reset = useCallback(() => {
    stopAll();
    queueRef.current = [];
    playIdxRef.current = 0;
    sentBufRef.current = "";
  }, [stopAll]);

  const playQueue = useCallback(async () => {
    if (playingRef.current) return;
    const gen = genRef.current;   // snapshot generation at entry
    playingRef.current = true;
    while (playIdxRef.current < queueRef.current.length) {
      const url = await queueRef.current[playIdxRef.current];
      playIdxRef.current++;
      // If stop/reset was called while the TTS fetch was in-flight, bail out
      if (genRef.current !== gen) break;
      if (!url || muted) continue;
      setSpeaking(true);
      await new Promise<void>((resolve) => {
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => { setSpeaking(false); resolve(); };
        audio.onerror = () => { setSpeaking(false); resolve(); };
        audio.play().catch(resolve);
      });
      // If stop/reset was called while audio was playing, bail out
      if (genRef.current !== gen) { setSpeaking(false); break; }
    }
    if (genRef.current === gen) playingRef.current = false;
  }, [muted]);

  const flushSentence = useCallback((text: string) => {
    const trimmed = text.trim();
    if (!trimmed || muted) return;
    // fire TTS immediately (non-blocking); queue the promise
    queueRef.current.push(api.speak(trimmed));
    playQueue();
  }, [muted, playQueue]);

  // Called for each streamed token
  const onToken = useCallback((token: string) => {
    sentBufRef.current += token;
    // Detect sentence boundary: punctuation followed by space or end
    const match = sentBufRef.current.match(/^([\s\S]*?[.!?])(\s+|$)/);
    if (match) {
      const sentence = match[1];
      sentBufRef.current = sentBufRef.current.slice(match[0].length);
      flushSentence(sentence);
    }
  }, [flushSentence]);

  // Called when stream ends — flush any text not yet spoken.
  // Do NOT fall back to fullText: sentences already flushed via onToken would play again.
  const onStreamEnd = useCallback((_fullText: string) => {
    const remainder = sentBufRef.current.trim();
    if (remainder) flushSentence(remainder);
    sentBufRef.current = "";
  }, [flushSentence]);

  // Play a complete (non-streamed) text all at once
  const playFull = useCallback((text: string) => {
    if (!text || muted) return;
    reset();
    queueRef.current.push(api.speak(text));
    playQueue();
  }, [muted, reset, playQueue]);

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
  sessionId,
  question,
  turnNumber,
  flags,
  onStreamedAnswer,
  onVoiceAnswer,
}: Props) {
  const [textAnswer, setTextAnswer] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [streamingQuestion, setStreamingQuestion] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [muted, setMuted] = useState(false);
  const abortRef = useRef<(() => void) | null>(null);

  const tts = useSentenceTTS(muted);
  // Set true when answer was streamed — so the question prop change doesn't replay TTS
  const skipNextTTSRef = useRef(false);

  // Play the current question via TTS when it changes (non-streaming path only)
  useEffect(() => {
    if (streamingQuestion !== null) return;
    if (skipNextTTSRef.current) { skipNextTTSRef.current = false; return; }
    tts.reset();
    if (question) tts.playFull(question);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [question]);

  const displayQuestion = streamingQuestion !== null ? streamingQuestion : question;
  const recentFlags = flags.slice(-3);

  // ── Text submit with streaming ──
  const submitText = useCallback(async (answer: string) => {
    if (!answer.trim() || submitting) return;
    setError("");
    setSubmitting(true);
    tts.reset();
    setStreamingQuestion("");

    let accumulated = "";
    const abort = api.submitAnswerStream(
      sessionId,
      answer.trim(),
      (token) => {
        accumulated += token;
        setStreamingQuestion(accumulated);
        tts.onToken(token);
      },
      (data) => {
        if (data.history_complete) {
          // Don't speak the final response — we're leaving this screen
          tts.stopAll();
        } else {
          tts.onStreamEnd(accumulated);
          skipNextTTSRef.current = true; // question prop will update; skip playFull
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
        setError(msg);
        setSubmitting(false);
        setStreamingQuestion(null);
      },
    );
    abortRef.current = abort;
  }, [submitting, sessionId, tts, onStreamedAnswer]);

  // ── Skip question ──
  const skipQuestion = useCallback(() => {
    submitText("I'd prefer to skip this question.");
  }, [submitText]);

  // ── Voice answer (already processed on server) ──
  const handleVoiceAnswer = useCallback((resp: AnswerResponse & { transcript: string }) => {
    if (resp.history_complete) {
      // Leaving the screen — stop any in-flight TTS
      tts.stopAll();
    } else {
      // Streaming tokens already started TTS for the next question via onToken;
      // just block the useEffect from calling playFull again when question prop updates
      skipNextTTSRef.current = true;
    }
    onVoiceAnswer(resp);
  }, [tts, onVoiceAnswer]);

  // ── Voice streaming tokens (from WS) ──
  const handleVoiceToken = useCallback((token: string) => {
    tts.onToken(token);
  }, [tts]);

  // Only flush remaining TTS buffer if we're continuing (not going to review)
  const handleVoiceStreamEnd = useCallback((fullText: string, historyComplete: boolean) => {
    if (!historyComplete) tts.onStreamEnd(fullText);
    else tts.stopAll();
  }, [tts]);

  useEffect(() => () => { abortRef.current?.(); }, []);

  return (
    <div className="space-y-5 fade-up">
      {/* AI Avatar */}
      <div className="flex flex-col items-center gap-3 pt-2 pb-4">
        <AIAvatar speaking={tts.speaking} loading={submitting} size="lg" />

        {/* Siri/Jarvis-style waveform */}
        <SiriWaveform active={tts.speaking} />

        <div className="flex items-center gap-2">
          <button
            onClick={() => setMuted((m) => { if (!m) tts.stopAll(); return !m; })}
            className="p-2 rounded-xl bg-white shadow-sm border border-slate-200 text-slate-500 hover:text-indigo-600 hover:border-indigo-200 transition-all"
          >
            {muted ? <VolumeX className="w-4 h-4" /> : <Volume2 className="w-4 h-4" />}
          </button>
          <button
            onClick={() => tts.replay(question)}
            className="p-2 rounded-xl bg-white shadow-sm border border-slate-200 text-slate-500 hover:text-indigo-600 hover:border-indigo-200 transition-all"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>

        <p className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
          {submitting
            ? "AI is thinking…"
            : tts.speaking
              ? "Speaking"
              : `Question ${turnNumber}`}
        </p>
      </div>

      {/* Question bubble — shows streaming tokens as they arrive */}
      <div className={clsx(
        "relative rounded-3xl p-6 transition-all duration-300",
        tts.speaking
          ? "bg-gradient-to-br from-indigo-50 to-violet-50 border-2 border-indigo-200 shadow-lg shadow-indigo-100"
          : "bg-white border border-slate-200 shadow-md"
      )}>
        <div
          className="absolute -top-3 left-6 w-6 h-6 rotate-45 rounded-sm"
          style={{
            background: tts.speaking ? "#e0e7ff" : "white",
            borderLeft: tts.speaking ? "2px solid #a5b4fc" : "1px solid #e2e8f0",
            borderTop: tts.speaking ? "2px solid #a5b4fc" : "1px solid #e2e8f0",
          }}
        />
        {submitting && streamingQuestion === "" ? (
          <div className="flex items-center gap-3 text-indigo-600">
            <svg className="animate-spin h-5 w-5 flex-shrink-0" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <span className="font-medium text-indigo-600">Thinking…</span>
          </div>
        ) : (
          <p className="text-lg font-semibold text-gray-800 leading-relaxed">
            {displayQuestion}
            {streamingQuestion !== null && submitting && (
              <span className="inline-block w-0.5 h-5 bg-indigo-500 ml-0.5 animate-pulse align-text-bottom" />
            )}
          </p>
        )}
      </div>

      {/* Clinical flags are intentionally hidden during patient Q&A — shown to doctor on review screen */}

      {/* Voice answer */}
      <div className="card space-y-3">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-600">
          <span className="w-7 h-7 rounded-lg bg-indigo-100 flex items-center justify-center text-indigo-600">🎤</span>
          <span>Speak your answer</span>
          <span className="text-xs text-slate-400 font-normal">— streamed, transcribed &amp; analysed instantly</span>
        </div>
        <VoiceRecorder
          sessionId={sessionId}
          onAnswer={handleVoiceAnswer}
          onToken={handleVoiceToken}
          onStreamEnd={(text, done) => handleVoiceStreamEnd(text, done)}
          disabled={submitting || tts.speaking}
        />
      </div>

      {/* Divider */}
      <div className="flex items-center gap-3">
        <div className="flex-1 border-t border-slate-200" />
        <span className="text-xs text-slate-400 font-medium bg-[#f5f4ff] px-2">or type</span>
        <div className="flex-1 border-t border-slate-200" />
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
            "self-end px-4 py-3 rounded-xl font-semibold transition-all duration-200 shadow-md",
            textAnswer.trim() && !submitting
              ? "bg-gradient-to-r from-indigo-600 to-violet-600 text-white hover:shadow-lg hover:shadow-indigo-500/30 active:scale-95"
              : "bg-slate-100 text-slate-400 cursor-not-allowed"
          )}
          onClick={() => submitText(textAnswer)}
          disabled={submitting || !textAnswer.trim()}
        >
          <Send className="w-4 h-4" />
        </button>
      </div>
      <div className="flex items-center justify-between -mt-2">
        <p className="text-xs text-slate-400">⌘ + Enter to submit</p>
        <button
          onClick={skipQuestion}
          disabled={submitting}
          className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
        >
          <SkipForward className="w-3.5 h-3.5" />
          Skip question
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm">
          {error}
        </div>
      )}
    </div>
  );
}
