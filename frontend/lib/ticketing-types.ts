// Types for the ticketing (pre-visit) flow

export interface TicketCategory {
  key: string;
  label: string;
}

export interface StartSessionResponse {
  session_id: string;
  ticket_number: string | null;
  patient_id: string;
  language: string;
  phase: string;
  status: string;
}

export interface SessionResultResponse {
  session_id: string;
  ticket_number: string | null;   // e.g. "TKT-000042" — the printable receipt ID
  phase: string;
  status: string;
  category: { key: string; label: string; source: "auto" | "manual" } | null;
  flags: TicketFlag[];
  summary: SOAPSummary | null;
  started_at: string | null;
  ended_at: string | null;
  patient: {
    patient_id: string;
    name: string | null;
    age: number | null;
    gender: string | null;
    phone: string;
  } | null;
  hospital_name: string | null;
}

export interface TicketFlag {
  flag_type: "CRITICAL_RED_FLAG" | "RED_FLAG" | "IMPORTANT" | "NOTE";
  description: string;
  raised_at?: string;
}

export interface SOAPSummary {
  subjective?: {
    chief_complaint?: string | null;
    history_of_presenting_illness?: string | null;
    past_medical_history?: string | null;
    surgical_history?: string | null;
    medications?: string | null;
    allergies?: string | null;
    family_history?: string | null;
    social_history?: string | null;
    review_of_systems?: string | null;
  } | null;
  objective?: {
    vital_signs?: string | null;
    physical_examination?: string | null;
  } | null;
  assessment?: string | null;
  plan?: string | null;
  full_transcript?: string | null;  // Add full transcript
}

// WebSocket events from server → client
export type TicketWSEvent =
  | { type: "ready"; session_id: string; phase: string; language: string; voice_mode?: "legacy" | "gemini_live" }
  | { type: "triage_started"; session_id: string; language: string }
  | { type: "category_identified"; category: TicketCategory; confidence: string }
  | { type: "category_manual_required"; categories: TicketCategory[] }
  | { type: "category_confirmed"; category: TicketCategory & { source: string } }
  | { type: "consultation_started"; category: string; starting_turn: number }
  | { type: "red_flag_raised"; flag: { flag_type: string; description: string } }
  | { type: "consultation_ended" }
  | { type: "result_ready"; summary: SOAPSummary | null; flags: TicketFlag[] }
  | { type: "session_partial"; session_id: string }
  | { type: "partial_transcript"; text: string }
  | { type: "silence_nudge" }
  | { type: "agent_speaking"; question: string; turn: number; audio_b64: string | null; mime?: string }
  | { type: "agent_done_speaking"; turn: number }
  | { type: "agent_audio_chunk"; audio_b64: string; mime?: string }
  | { type: "interrupt" }
  | { type: "user_speech_started" }
  | { type: "turn_complete"; turn: number; next_question: string | null; phase: string; history_complete: boolean; new_flags: TicketFlag[] }
  | { type: "ended"; session_id: string }
  | { type: "error"; message: string; fatal?: boolean }
  | { type: "pong" };

// Admin types
export interface AdminSession {
  session_id: string;
  ticket_number: string | null;
  hospital_id: string;
  patient_id: string;
  phase: string;
  status: string;
  category: { key: string; label: string; source: string } | null;
  language: string;
  turn_count: number;
  started_at: string | null;
  ended_at: string | null;
  deleted_at: string | null;
  started_at_ist: string | null;
  ended_at_ist: string | null;
  deleted_at_ist: string | null;
  flags: TicketFlag[];
}

export interface Hospital {
  hospital_id: string;
  slug: string;
  name: string;
  default_language: string;
  created_at: string;
}
