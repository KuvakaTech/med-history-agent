"use client";
import { useEffect, useRef, useState } from "react";
import type { DiagnosisResult, PipelineEvent, PipelineStep } from "@/lib/types";
import { api } from "@/lib/api";
import AIAvatar from "./AIAvatar";
import clsx from "clsx";

interface Props {
  sessionId: string;
  onComplete: (note: Record<string, unknown>, diagnosis: DiagnosisResult) => void;
}

type StepState = "pending" | "running" | "done" | "error";

interface Step {
  id: PipelineStep;
  label: string;
  state: StepState;
}

const INITIAL_STEPS: Step[] = [
  { id: "translate", label: "Detecting language & translating", state: "pending" },
  { id: "completeness", label: "Checking completeness", state: "pending" },
  { id: "summarize", label: "Generating clinical note (SOAP)", state: "pending" },
  { id: "diagnose", label: "Running AI diagnosis", state: "pending" },
];

const STEP_ICON: Record<StepState, string> = {
  pending: "○",
  running: "◌",
  done: "✓",
  error: "✕",
};

export default function ProcessingScreen({ sessionId, onComplete }: Props) {
  const [steps, setSteps] = useState<Step[]>(INITIAL_STEPS);
  const [error, setError] = useState("");
  // Stable ref so onComplete prop changes never restart the EventSource
  const onCompleteRef = useRef(onComplete);
  useEffect(() => { onCompleteRef.current = onComplete; });

  const anyRunning = steps.some(s => s.state === "running");

  useEffect(() => {
    let es: EventSource;
    let cancelled = false;

    api.pipelineUrl(sessionId).then((url) => {
      if (cancelled) return;
      es = new EventSource(url);

    es.onmessage = (e) => {
      // Ignore SSE keepalive comments (they arrive as empty data)
      if (!e.data || e.data.trim() === "") return;

      let event: PipelineEvent;
      try { event = JSON.parse(e.data); } catch { return; }

      if (event.event === "step" && event.step) {
        setSteps((prev) =>
          prev.map((s) => s.id === event.step ? { ...s, state: event.status as StepState } : s)
        );
      } else if (event.event === "complete") {
        es.close();
        onCompleteRef.current(
          (event.note as Record<string, unknown>) ?? {},
          (event.diagnosis as DiagnosisResult) ?? { differential_diagnoses: [], urgent_concerns: [], suggested_workup: [] }
        );
      } else if (event.event === "error") {
        setError(event.message || "Pipeline failed");
        setSteps((prev) => prev.map((s) => s.state === "running" ? { ...s, state: "error" } : s));
        es.close();
      }
    };

      es.onerror = () => {
        if (es.readyState !== EventSource.CLOSED) {
          setError("Connection lost. Please refresh and try again.");
          setSteps((prev) => prev.map((s) => s.state === "running" ? { ...s, state: "error" } : s));
        }
        es.close();
      };
    });

    return () => { cancelled = true; es?.close(); };
  }, [sessionId]); // onComplete intentionally excluded — stable via ref above

  return (
    <div className="flex flex-col items-center space-y-8 py-8 fade-up">
      {/* Animated orb */}
      <AIAvatar speaking={anyRunning} loading={anyRunning} size="lg" />

      <div className="text-center">
        <h2 className="text-xl font-bold text-gray-800">Analysing your responses…</h2>
        <p className="text-slate-500 text-sm mt-1">This takes 15–30 seconds. Please wait.</p>
      </div>

      {/* Steps */}
      <div className="w-full max-w-sm space-y-3">
        {steps.map((step, i) => (
          <div
            key={step.id}
            className={clsx(
              "flex items-center gap-4 p-4 rounded-2xl border transition-all duration-300",
              step.state === "done" && "bg-green-50 border-green-200",
              step.state === "running" && "bg-indigo-50 border-indigo-200 shadow-md shadow-indigo-100",
              step.state === "pending" && "bg-white border-slate-100 opacity-50",
              step.state === "error" && "bg-red-50 border-red-200",
            )}
          >
            <div className={clsx(
              "w-8 h-8 rounded-xl flex items-center justify-center font-bold text-sm flex-shrink-0",
              step.state === "done" && "bg-green-500 text-white",
              step.state === "running" && "shimmer-bg text-white animate-pulse",
              step.state === "pending" && "bg-slate-200 text-slate-500",
              step.state === "error" && "bg-red-500 text-white",
            )}>
              {step.state === "running" ? (
                <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                STEP_ICON[step.state]
              )}
            </div>
            <span className={clsx(
              "text-sm font-medium",
              step.state === "done" && "text-green-700",
              step.state === "running" && "text-indigo-700 font-semibold",
              step.state === "pending" && "text-slate-400",
              step.state === "error" && "text-red-600",
            )}>
              {step.label}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm w-full max-w-sm">
          {error}
        </div>
      )}
    </div>
  );
}
