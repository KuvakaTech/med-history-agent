export type Specialty = "general_medicine" | "psychotherapy" | "gynecology";

export interface ClinicalFlag {
  flag_type: "CRITICAL_RED_FLAG" | "RED_FLAG" | "IMPORTANT" | "NOTE";
  description: string;
  raised_at?: string;
}

export interface QAEntry {
  question_id: string;
  question_text: string;
  answer: string;
  timestamp: string;
}

export interface DifferentialDiagnosis {
  condition: string;
  likelihood: "High" | "Medium" | "Low";
  reasoning: string;
  icd_code?: string;
}

export interface DiagnosisResult {
  differential_diagnoses: DifferentialDiagnosis[];
  urgent_concerns: string[];
  suggested_workup: string[];
  physician_note?: string;
}

export interface Medication {
  drug_name: string;
  dose: string;
  frequency: string;
  duration: string;
  instructions?: string;
  warnings?: string;
}

export interface PrescriptionResult {
  pharmacological: Medication[];
  non_pharmacological: string[];
  follow_up?: string;
  referrals: string[];
  contraindication_warnings: string[];
}

export interface StartResponse {
  session_id: string;
  specialty: string;
  stage: string;
  opening_question: string;
}

export interface AnswerResponse {
  new_flags: ClinicalFlag[];
  next_question: string | null;
  history_complete: boolean;
}

export interface QALogResponse {
  qa_log: QAEntry[];
  flags: ClinicalFlag[];
  raw_transcript: string;
  translated_transcript: string;
}

export type PipelineStep =
  | "translate"
  | "completeness"
  | "summarize"
  | "diagnose";

export interface PipelineEvent {
  event: "step" | "complete" | "error";
  step?: PipelineStep;
  status?: "running" | "done";
  label?: string;
  message?: string;
  note?: Record<string, unknown>;
  diagnosis?: DiagnosisResult;
}

export interface VoiceStreamEvent {
  type: "ready" | "ack" | "processing" | "transcript" | "token" | "done" | "answer" | "error";
  bytes?: number;
  stage?: string;
  text?: string;
  transcript?: string;
  next_question?: string | null;
  history_complete?: boolean;
  new_flags?: ClinicalFlag[];
  message?: string;
}

export type ConsultationScreen =
  | "questionnaire"
  | "review"
  | "processing"
  | "results";
