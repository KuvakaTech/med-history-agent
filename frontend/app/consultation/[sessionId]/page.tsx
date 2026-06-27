"use client";
import { useParams, useSearchParams } from "next/navigation";
import { useState } from "react";
import type {
  AnswerResponse,
  ClinicalFlag,
  ConsultationScreen,
  DiagnosisResult,
  QAEntry,
} from "@/lib/types";
import { api } from "@/lib/api";
import QuestionnaireScreen from "@/components/QuestionnaireScreen";
import ReviewScreen from "@/components/ReviewScreen";
import ProcessingScreen from "@/components/ProcessingScreen";
import ResultsScreen from "@/components/ResultsScreen";
import clsx from "clsx";

const SCREEN_STEPS: ConsultationScreen[] = ["questionnaire", "review", "processing", "results"];
const STEP_LABELS: Record<ConsultationScreen, string> = {
  questionnaire: "History Taking",
  review: "Review",
  processing: "Analysis",
  results: "Results",
};

export default function ConsultationPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const sessionId = params.sessionId as string;
  const initialQuestion = searchParams.get("q") || "";

  const [screen, setScreen] = useState<ConsultationScreen>("questionnaire");
  const [currentQuestion, setCurrentQuestion] = useState(initialQuestion);
  const [turnNumber, setTurnNumber] = useState(1);
  const [flags, setFlags] = useState<ClinicalFlag[]>([]);
  const [qaLog, setQaLog] = useState<QAEntry[]>([]);
  const [note, setNote] = useState<Record<string, unknown> | null>(null);
  const [diagnosis, setDiagnosis] = useState<DiagnosisResult | null>(null);

  const applyAnswer = async (resp: AnswerResponse) => {
    setFlags((prev) => [...prev, ...resp.new_flags]);
    setTurnNumber((n) => n + 1);
    if (resp.history_complete) {
      const log = await api.getQALog(sessionId);
      setQaLog(log.qa_log);
      setFlags(log.flags);
      setScreen("review");
    } else {
      setCurrentQuestion(resp.next_question || "");
    }
  };

  const handleStreamedAnswer = (resp: AnswerResponse) => { applyAnswer(resp); };
  const handleVoiceAnswer = (resp: AnswerResponse & { transcript: string }) => { applyAnswer(resp); };

  const handleProceed = () => setScreen("processing");
  const handlePipelineComplete = (
    noteData: Record<string, unknown>,
    dxData: DiagnosisResult
  ) => {
    setNote(noteData);
    setDiagnosis(dxData);
    setScreen("results");
  };

  const currentStep = SCREEN_STEPS.indexOf(screen);

  return (
    <main className="min-h-screen flex flex-col bg-[#f5f4ff]">
      {/* Header */}
      <header className="bg-[#0a0f1e] text-white px-5 py-3.5 flex items-center justify-between shadow-xl sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xl shimmer-bg flex items-center justify-center text-sm shadow-lg">⚕️</div>
          <div>
            <div className="font-bold text-sm leading-tight">kuvaka Clinical AI</div>
            <div className="text-slate-400 text-xs">{STEP_LABELS[screen]}</div>
          </div>
        </div>

        {/* Step progress */}
        <div className="hidden sm:flex items-center gap-1.5">
          {SCREEN_STEPS.map((s, i) => (
            <div key={s} className="flex items-center gap-1.5">
              <div className={clsx(
                "w-2 h-2 rounded-full transition-all duration-300",
                i < currentStep ? "bg-indigo-400" :
                i === currentStep ? "bg-white w-3 h-3" : "bg-slate-700"
              )} />
              {i < SCREEN_STEPS.length - 1 && (
                <div className={clsx("w-8 h-px", i < currentStep ? "bg-indigo-400" : "bg-slate-700")} />
              )}
            </div>
          ))}
        </div>

        <div className="text-xs text-slate-500 font-mono">
          {sessionId.slice(0, 8)}
        </div>
      </header>

      {/* Critical flags banner */}
      {flags.some(f => f.flag_type === "CRITICAL_RED_FLAG") && (
        <div className="bg-red-600 text-white text-xs font-semibold text-center py-2 px-4 flex items-center justify-center gap-2">
          🚨 Critical clinical alert detected — physician review required immediately
        </div>
      )}

      {/* Screen content */}
      <div className="flex-1 flex flex-col items-center px-4 py-6">
        <div className="w-full max-w-xl">
          {screen === "questionnaire" && (
            <QuestionnaireScreen
              sessionId={sessionId}
              question={currentQuestion}
              turnNumber={turnNumber}
              flags={flags}
              onStreamedAnswer={handleStreamedAnswer}
              onVoiceAnswer={handleVoiceAnswer}
            />
          )}
          {screen === "review" && (
            <ReviewScreen sessionId={sessionId} qaLog={qaLog} flags={flags} onProceed={handleProceed} />
          )}
          {screen === "processing" && (
            <ProcessingScreen sessionId={sessionId} onComplete={handlePipelineComplete} />
          )}
          {screen === "results" && (
            <ResultsScreen sessionId={sessionId} note={note} diagnosis={diagnosis} />
          )}
        </div>
      </div>
    </main>
  );
}
