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

export interface GrievanceRecord {
  full_name?: string | null;
  father_guardian_name?: string | null;
  age?: number | null;
  is_senior_citizen?: boolean | null;
  is_divyang?: boolean | null;
  residential_address?: GrievanceAddress | null;
  complaint_location_same_as_home?: boolean | null;
  complaint_address?: GrievanceAddress | null;
  category?: string | null;
  sub_category?: string | null;
  verbatim_problem?: string | null;
  confirmed_summary?: string | null;
  since_when?: string | null;
  affected_count?: string | null;
  prior_action?: string | null;
  desired_outcome?: string | null;
  department_tag?: string | null;
  urgency?: string | null;
  sentiment?: string | null;
  has_photos_or_docs?: boolean | null;
  optional_email?: string | null;
  category_details?: Record<string, unknown>;
}

export type LessonTopic =
  | "Ghar"
  | "Khana"
  | "Jaanwar"
  | "Rang"
  | "Ginti"
  | "Shareer"
  | "Guddi-choose";

export interface WordPracticeResult {
  word: string;
  result: "clear" | "emerging" | "not_yet";
  said_in_dialect: boolean;
}

export interface DialectBridge {
  child_word: string;
  hindi_word: string;
}

export interface LearningRecord {
  learner_name?: string | null;
  date?: string | null;
  duration_est?: number | null;
  mode_used?: string | null;
  mood_start?: string | null;
  topic?: string | null;
  words_practiced?: WordPracticeResult[];
  new_words_clear?: number | null;
  emerging_words?: number | null;
  pronunciation_note?: string | null;
  dialect_bridges?: DialectBridge[];
  milestone_signal?: string | null;
  engagement?: string | null;
  flags?: string | null;
  next_focus?: string[];
  friendly_summary?: string | null;
}

export interface StartSessionBody {
  phone?: string;
  language?: string;
  gender?: string;
  learner_name?: string;
  lesson_topic?: LessonTopic;
}

export interface StartSessionResponse {
  session_id: string;
  phone?: string | null;
  language: string;
  phase: string;
  status: string;
  learner_name?: string | null;
  lesson_topic?: string | null;
}

export interface CentreResponse {
  slug: string;
  name: string;
  default_language: string;
  centre_kind: "grievance" | "learning";
}

export interface KioskTranscriptEntry {
  speaker: "user" | "agent";
  text: string;
}

export interface SessionResultResponse {
  session_id: string;
  centre_kind: "grievance" | "learning";
  complaint_number?: string | null;
  phase: string;
  status: string;
  phone?: string | null;
  language: string;
  gender?: string;
  learner_name?: string | null;
  lesson_topic?: string | null;
  grievance?: GrievanceRecord | null;
  learning_record?: LearningRecord | null;
  full_transcript?: string | null;
  transcript?: KioskTranscriptEntry[];
  started_at?: string | null;
  ended_at?: string | null;
  centre_name?: string | null;
}

/** @deprecated use SessionResultResponse */
export type GrievanceResultResponse = SessionResultResponse;

export type KioskWSEvent = {
  type: string;
  session_id?: string;
  phase?: string;
  language?: string;
  voice_mode?: string;
  message?: string;
  fatal?: boolean;
  text?: string;
  question?: string;
  turn?: number;
  audio_b64?: string;
  complaint_number?: string;
  grievance?: GrievanceRecord;
  learning_record?: LearningRecord;
  word_id?: string;
  hindi?: string;
  image_url?: string;
  mode?: "teach" | "quiz";
  child_said?: string;
  result?: "clear" | "close" | "wrong";
  expected_hindi?: string;
};

export const LESSON_TOPICS: {
  value: LessonTopic;
  label: string;
  coverImage: string;
}[] = [
  { value: "Ghar", label: "घर", coverImage: "/kiosk/vocabulary/ghar/ghar.jpg" },
  { value: "Khana", label: "खाना", coverImage: "/kiosk/vocabulary/khana/aam.jpg" },
  { value: "Jaanwar", label: "जानवर", coverImage: "/kiosk/vocabulary/jaanwar/bakri.jpg" },
  { value: "Rang", label: "रंग", coverImage: "/kiosk/vocabulary/rang/laal.svg" },
  { value: "Ginti", label: "गिनती", coverImage: "/kiosk/vocabulary/ginti/ek.svg" },
  { value: "Shareer", label: "शरीर", coverImage: "/kiosk/vocabulary/shareer/aankh.jpg" },
  {
    value: "Guddi-choose",
    label: "गुड्डी चुनें",
    coverImage: "/kiosk/vocabulary/topics/guddi.svg",
  },
];

export function isLearningSlug(slug: string): boolean {
  return slug === "barwani-guddi";
}

export function isJanSunwaiSlug(slug: string): boolean {
  return slug === "varanasi-jan-sunwai" || slug === "varanasi-jan-sunwai-v2";
}
