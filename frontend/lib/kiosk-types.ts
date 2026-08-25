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

export interface StartSessionResponse {
  session_id: string;
  phone: string;
  language: string;
  phase: string;
  status: string;
}

export interface CentreResponse {
  slug: string;
  name: string;
  default_language: string;
}

export interface KioskTranscriptEntry {
  speaker: "user" | "agent";
  text: string;
}

export interface GrievanceResultResponse {
  session_id: string;
  complaint_number?: string | null;
  phase: string;
  status: string;
  phone: string;
  language: string;
  gender: string;
  grievance?: GrievanceRecord | null;
  full_transcript?: string | null;
  transcript?: KioskTranscriptEntry[];
  started_at?: string | null;
  ended_at?: string | null;
  centre_name?: string | null;
}

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
};
