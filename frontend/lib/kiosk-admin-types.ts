export interface KioskCentre {
  centre_id: string;
  slug: string;
  name: string;
  default_language: string;
  prompt_file?: string | null;
  complaint_prefix?: string | null;
}

export interface KioskAdminSession {
  session_id: string;
  centre_id: string;
  complaint_number?: string | null;
  phone: string;
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
  grievance?: Record<string, unknown> | null;
}

export interface KioskAdminSessionDetail extends KioskAdminSession {
  transcript?: Array<{ speaker: string; text: string }>;
  full_transcript?: string | null;
  centre_name?: string | null;
  grievance?: Record<string, unknown> | null;
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
