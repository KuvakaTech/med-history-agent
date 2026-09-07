export interface KioskCentre {
  centre_id: string;
  slug: string;
  name: string;
  default_language: string;
  centre_kind?: "grievance" | "learning";
  prompt_file?: string | null;
  complaint_prefix?: string | null;
}

export interface LearningRecord {
  learner_name?: string | null;
  topic?: string | null;
  friendly_summary?: string | null;
  words_practiced?: Array<{
    word: string;
    result: string;
    said_in_dialect: boolean;
  }>;
  mode_used?: string | null;
  mood_start?: string | null;
  engagement?: string | null;
  flags?: string | null;
  next_focus?: string[];
  milestone_signal?: string | null;
  pronunciation_note?: string | null;
  new_words_clear?: number | null;
  emerging_words?: number | null;
}

export interface KioskAdminSession {
  session_id: string;
  centre_id: string;
  complaint_number?: string | null;
  phone?: string | null;
  learner_name?: string | null;
  lesson_topic?: string | null;
  language: string;
  gender: string;
  phase: string;
  status: string;
  turn_count?: number;
  started_at?: string;
  ended_at?: string | null;
  started_at_ist?: string | null;
  ended_at_ist?: string | null;
  deleted_at_ist?: string | null;
  grievance_summary?: string | null;
  session_summary?: string | null;
  grievance?: Record<string, unknown> | null;
  learning_record?: LearningRecord | null;
}

export interface KioskAdminSessionDetail extends KioskAdminSession {
  centre_kind?: "grievance" | "learning";
  transcript?: Array<{ speaker: string; text: string }>;
  full_transcript?: string | null;
  centre_name?: string | null;
}

export interface GrievanceAddress {
  house?: string | null;
  street?: string | null;
  village_mohalla?: string | null;
  gp_ward?: string | null;
  tehsil?: string | null;
  block?: string | null;
  post_office?: string | null;
  pin_code?: string | null;
  landmark?: string | null;
}
