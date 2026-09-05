"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { Mic, Square, Loader2 } from "lucide-react";
import type { AnswerResponse, VoiceStreamEvent } from "@/lib/types";
import { api } from "@/lib/api";
import clsx from "clsx";

type Stage = "idle" | "connecting" | "recording" | "transcribing" | "thinking" | "error";

interface Props {
  sessionId: string;
  onAnswer: (resp: AnswerResponse & { transcript: string }) => void;
  onToken?: (token: string) => void;
  onStreamEnd?: (fullText: string, historyComplete: boolean) => void;
  onRecordingStart?: () => void;
  onStageChange?: (stage: Stage) => void;
  onRetry?: (message: string) => void;
  disabled?: boolean;
}

function detectMime(): string {
  for (const m of [
    "audio/webm;codecs=opus",
    "audio/ogg;codecs=opus",
    "audio/mp4;codecs=mp4a.40.2", // Safari — AAC
    "audio/mp4",
    "audio/aac",
    "audio/mpeg",
    "audio/webm",
    "audio/ogg",
    "audio/wav",
  ]) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "audio/webm";
}

// Mirrored oscilloscope + volume meter for live mic input
function LiveMicWaveform({ analyser }: { analyser: AnalyserNode | null }) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const smoothVolRef = useRef(0);
  const tooQuietRef = useRef(false);
  const [volSegs, setVolSegs] = useState<boolean[]>(new Array(20).fill(false));
  const [tooQuiet, setTooQuiet] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas) return;

    const W = Math.max(wrap?.clientWidth ?? 320, 200);
    const H = 80;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    canvas.style.width = `${W}px`;
    canvas.style.height = `${H}px`;

    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);

    const bufLen = analyser?.fftSize ?? 256;
    const td = analyser ? new Uint8Array(bufLen) : null;
    let rafId = 0;
    let lastVolUpdate = 0;
    let lastQuietCheck = 0;

    const draw = (ts: number) => {
      ctx.clearRect(0, 0, W, H);

      // Subtle dashed center baseline
      ctx.save();
      ctx.beginPath();
      ctx.strokeStyle = "rgba(51,4,159,0.1)";
      ctx.lineWidth = 1;
      ctx.setLineDash([2, 8]);
      ctx.moveTo(0, H / 2);
      ctx.lineTo(W, H / 2);
      ctx.stroke();
      ctx.restore();

      if (analyser && td) {
        analyser.getByteTimeDomainData(td);

        let maxDev = 0;
        const pts: [number, number][] = Array.from({ length: bufLen }, (_, i) => {
          const v = td[i] / 128 - 1; // –1..1
          if (Math.abs(v) > maxDev) maxDev = Math.abs(v);
          return [(i / (bufLen - 1)) * W, H / 2 + v * (H / 2 - 8)];
        });
        // Mirror: y reflected around center
        const mPts: [number, number][] = pts.map(([x, y]) => [x, H - y]);

        // Smooth volume
        smoothVolRef.current += (maxDev - smoothVolRef.current) * 0.12;
        const sv = smoothVolRef.current;
        const fillA = 0.07 + sv * 0.2;

        // Upper fill (waveform → center)
        ctx.beginPath();
        pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.lineTo(W, H / 2);
        ctx.lineTo(0, H / 2);
        ctx.closePath();
        const gUp = ctx.createLinearGradient(0, 4, 0, H / 2);
        gUp.addColorStop(0, `rgba(51,4,159,${fillA})`);
        gUp.addColorStop(1, "rgba(51,4,159,0.01)");
        ctx.fillStyle = gUp;
        ctx.fill();

        // Lower fill (mirrored waveform → center)
        ctx.beginPath();
        mPts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.lineTo(W, H / 2);
        ctx.lineTo(0, H / 2);
        ctx.closePath();
        const gDn = ctx.createLinearGradient(0, H / 2, 0, H - 4);
        gDn.addColorStop(0, "rgba(51,4,159,0.01)");
        gDn.addColorStop(1, `rgba(51,4,159,${fillA})`);
        ctx.fillStyle = gDn;
        ctx.fill();

        // Waveform lines
        const lineA = 0.4 + sv * 0.6;
        ctx.globalAlpha = lineA;
        ctx.strokeStyle = "#33049f";
        ctx.lineWidth = 1.5;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.shadowColor = "rgba(51,4,159,0.35)";
        ctx.shadowBlur = sv > 0.08 ? 6 : 0;

        ctx.beginPath();
        pts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.stroke();

        ctx.beginPath();
        mPts.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
        ctx.stroke();

        ctx.globalAlpha = 1;
        ctx.shadowBlur = 0;

        // Throttled React state updates
        if (ts - lastVolUpdate > 80) {
          lastVolUpdate = ts;
          const segs = Array.from({ length: 20 }, (_, i) => sv > (i / 20) * 0.75);
          setVolSegs(segs);
        }
        if (ts - lastQuietCheck > 700) {
          lastQuietCheck = ts;
          const quiet = maxDev < 0.05;
          if (quiet !== tooQuietRef.current) {
            tooQuietRef.current = quiet;
            setTooQuiet(quiet);
          }
        }
      }

      rafId = requestAnimationFrame(draw);
    };

    rafId = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafId);
  }, [analyser]);

  return (
    <div ref={wrapRef} className="space-y-2">
      <canvas ref={canvasRef} className="block rounded-lg" />
      {/* Volume meter */}
      <div className="flex items-center gap-2 px-0.5">
        <div className="flex gap-[3px] flex-1 h-[4px]">
          {volSegs.map((active, i) => (
            <div
              key={i}
              className="flex-1 rounded-full"
              style={{
                background: active ? "#33049f" : "#ede9fe",
                opacity: active ? 1 : 0.5,
                transition: "background 60ms ease",
              }}
            />
          ))}
        </div>
        {tooQuiet && (
          <span className="text-[11px] text-slate-400 shrink-0 flex items-center gap-1">
            <Mic className="w-2.5 h-2.5" />
            speak louder
          </span>
        )}
      </div>
    </div>
  );
}

export default function VoiceRecorder({
  sessionId, onAnswer, onToken, onStreamEnd, onRecordingStart, onStageChange, onRetry, disabled,
}: Props) {
  const [stage, setStage] = useState<Stage>("idle");
  const [elapsed, setElapsed] = useState(0);
  const [transcript, setTranscript] = useState("");
  const [streamedQuestion, setStreamedQuestion] = useState("");
  const [errorMsg, setErrorMsg] = useState("");
  const [displayAnalyser, setDisplayAnalyser] = useState<AnalyserNode | null>(null);

  const setStageAndNotify = useCallback((next: Stage) => {
    setStage(next);
    onStageChange?.(next);
  }, [onStageChange]);

  const wsRef = useRef<WebSocket | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const questionBufRef = useRef("");
  const audioCtxRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);

  const stopAnalyser = useCallback(() => {
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    analyserRef.current = null;
    setDisplayAnalyser(null);
  }, []);

  const setupAnalyser = useCallback((stream: MediaStream) => {
    try {
      const ctx = new (window.AudioContext || (window as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext!)();
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;             // 128 freq bins; fftSize = time-domain buffer
      analyser.smoothingTimeConstant = 0.8;
      ctx.createMediaStreamSource(stream).connect(analyser);
      audioCtxRef.current = ctx;
      analyserRef.current = analyser;
      setDisplayAnalyser(analyser);       // canvas component owns the RAF loop
    } catch {
      // AudioContext not available — recording still works, just no viz
    }
  }, []);

  const cleanup = useCallback(() => {
    timerRef.current && clearInterval(timerRef.current);
    recorderRef.current?.state !== "inactive" && recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    wsRef.current?.readyState === WebSocket.OPEN && wsRef.current.close();
    wsRef.current = null;
    recorderRef.current = null;
    streamRef.current = null;
    timerRef.current = null;
    stopAnalyser();
  }, [stopAnalyser]);

  useEffect(() => () => cleanup(), [cleanup]);

  const start = useCallback(async () => {
    setErrorMsg("");
    setTranscript("");
    setStreamedQuestion("");
    questionBufRef.current = "";
    setElapsed(0);
    setStageAndNotify("connecting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      setErrorMsg("Microphone access denied.");
      setStageAndNotify("error");
      return;
    }
    streamRef.current = stream;
    setupAnalyser(stream);

    const mime = detectMime();
    let mr: MediaRecorder;
    try {
      mr = new MediaRecorder(stream, { mimeType: mime, audioBitsPerSecond: 32000 });
    } catch {
      mr = new MediaRecorder(stream); // browser default format
    }
    recorderRef.current = mr;
    // The browser may pick a different format than requested — report the real one
    const actualMime = mr.mimeType || mime;

    const wsUrl = await api.voiceStreamUrl(sessionId);
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    mr.ondataavailable = (e) => {
      if (e.data.size > 0 && ws.readyState === WebSocket.OPEN) ws.send(e.data);
    };

    ws.onopen = () => ws.send(JSON.stringify({ type: "start", mime_type: actualMime }));

    ws.onmessage = (ev) => {
      if (typeof ev.data !== "string") return;
      const msg: VoiceStreamEvent = JSON.parse(ev.data);

      if (msg.type === "ready") {
        setStageAndNotify("recording");
        onRecordingStart?.();
        timerRef.current = setInterval(() => setElapsed((n) => n + 1), 1000);
        mr.start(250);
      } else if (msg.type === "transcript") {
        setTranscript(msg.text || "");
        setStageAndNotify("thinking");
        stopAnalyser(); // stop mic visualizer once transcription done
      } else if (msg.type === "processing") {
        if (msg.stage === "transcribing") setStageAndNotify("transcribing");
        else if (msg.stage === "thinking") setStageAndNotify("thinking");
      } else if (msg.type === "token") {
        const tok = msg.text || "";
        questionBufRef.current += tok;
        setStreamedQuestion(questionBufRef.current);
        onToken?.(tok);
      } else if (msg.type === "done") {
        const fullQuestion = questionBufRef.current;
        const histComplete = msg.history_complete ?? false;
        onStreamEnd?.(fullQuestion, histComplete);
        cleanup();
        setStageAndNotify("idle");
        setTranscript("");
        setStreamedQuestion("");
        questionBufRef.current = "";
        setElapsed(0);
        onAnswer({
          transcript: msg.transcript || "",
          next_question: msg.next_question ?? null,
          history_complete: msg.history_complete ?? false,
          new_flags: (msg.new_flags as AnswerResponse["new_flags"]) ?? [],
        });
      } else if (msg.type === "retry") {
        cleanup();
        setStageAndNotify("idle");
        setTranscript("");
        setStreamedQuestion("");
        questionBufRef.current = "";
        setElapsed(0);
        onRetry?.(msg.message ?? "We couldn't understand that. Please try again.");
      } else if (msg.type === "error") {
        if (msg.message) console.error("voice-stream error:", msg.message);
        setErrorMsg("Voice processing failed. Please try again.");
        setStageAndNotify("error");
        cleanup();
      }
    };

    ws.onerror = () => { setErrorMsg("Connection to server failed."); setStageAndNotify("error"); cleanup(); };
    ws.onclose = (ev) => {
      if (ev.code !== 1000 && (stage === "recording" || stage === "connecting")) {
        setErrorMsg("Connection closed unexpectedly.");
        setStageAndNotify("error");
      }
    };
  }, [sessionId, onAnswer, onToken, onStreamEnd, onRecordingStart, onRetry, cleanup, setupAnalyser, stopAnalyser, stage, setStageAndNotify]);

  const stop = useCallback(() => {
    timerRef.current && clearInterval(timerRef.current);
    timerRef.current = null;
    recorderRef.current?.state !== "inactive" && recorderRef.current?.stop();
    stopAnalyser();
    setTimeout(() => {
      wsRef.current?.readyState === WebSocket.OPEN &&
        wsRef.current.send(JSON.stringify({ type: "stop" }));
      setStage("transcribing");
    }, 200);
  }, [stopAnalyser]);

  const fmt = (s: number) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const isProcessing = stage === "transcribing" || stage === "thinking";

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3 flex-wrap">
        {stage === "idle" || stage === "error" ? (
          <button
            onClick={start}
            disabled={disabled}
            className={clsx(
              "flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm",
              "bg-brand hover:bg-brand-dark text-white shadow-sm active:scale-95 transition-all",
              disabled && "opacity-40 cursor-not-allowed"
            )}
          >
            <Mic className="w-4 h-4" />
            Speak your answer
          </button>
        ) : stage === "connecting" ? (
          <button disabled className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm bg-gray-100 text-gray-500 cursor-wait">
            <Loader2 className="w-4 h-4 animate-spin" /> Connecting…
          </button>
        ) : stage === "recording" ? (
          <button onClick={stop} className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm bg-red-500 hover:bg-red-600 text-white shadow-sm active:scale-95 transition-all">
            <Square className="w-4 h-4 fill-white" /> Stop recording
          </button>
        ) : (
          <button disabled className="flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-sm bg-gray-100 text-gray-500 cursor-wait">
            <Loader2 className="w-4 h-4 animate-spin" />
            {stage === "transcribing" ? "Transcribing…" : "AI thinking…"}
          </button>
        )}

        {stage === "recording" && (
          <div className="flex items-center gap-2 px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-red-600 text-sm font-mono font-medium">
            <span className="w-2 h-2 rounded-full bg-red-500 animate-ping" />
            {fmt(elapsed)}
          </div>
        )}
      </div>

      {/* Live mic waveform during recording */}
      {stage === "recording" && (
        <div className="px-4 py-3 bg-white border border-slate-200 rounded-lg shadow-sm space-y-2">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse shrink-0" />
            <span className="text-xs text-slate-500 font-medium tracking-wide">Recording</span>
          </div>
          <LiveMicWaveform analyser={displayAnalyser} />
        </div>
      )}

      {/* Transcribing / thinking / streamed response */}
      {(isProcessing || streamedQuestion) && (
        <div className={clsx(
          "rounded-lg border-2 p-3 text-sm min-h-[56px] transition-all",
          stage === "transcribing" && "border-amber-200 bg-amber-50/50",
          (stage === "thinking" || streamedQuestion) && "border-brand/20 bg-brand-light/40",
        )}>
          {stage === "transcribing" && (
            <span className="text-amber-700 flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" /> Transcribing…
            </span>
          )}
          {stage === "thinking" && !streamedQuestion && (
            <span className="text-brand flex items-center gap-2">
              <Loader2 className="w-3 h-3 animate-spin" />
              {transcript ? <span className="text-gray-600 italic">"{transcript}"</span> : "AI thinking…"}
            </span>
          )}
          {streamedQuestion && (
            <p className="text-gray-700 font-medium leading-relaxed">
              {streamedQuestion}
              <span className="inline-block w-0.5 h-4 bg-brand ml-0.5 animate-pulse align-middle" />
            </p>
          )}
        </div>
      )}

      {stage === "error" && errorMsg && (
        <p className="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">
          {errorMsg}
        </p>
      )}
    </div>
  );
}
