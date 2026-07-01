import type {
  AnswerResponse,
  ConsultationSummary,
  Patient,
  PrescriptionResult,
  QALogResponse,
  Specialty,
  StartResponse,
} from "./types";
import { setUser, clearAuth, type User } from "./auth";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001";
const API = `${BASE}/api/v1`;

// ── Token management ──────────────────────────────────────────────────────────
// Access token: in-memory only (15 min). Refresh token: httpOnly cookie (7 days).
// On expiry /auth/refresh is tried first; if that fails the user must log in again.

let _token: string | null = null;
let _tokenExpiry: number = 0;

interface TokenPayload {
  access_token: string;
  expires_in: number;
  user: User;
}

function _cache(data: TokenPayload): string {
  _token = data.access_token;
  _tokenExpiry = Date.now() + (data.expires_in - 30) * 1000;
  setUser(data.user);
  return _token;
}

async function _refresh(): Promise<string> {
  const res = await fetch(`${API}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  if (!res.ok) throw new Error("refresh_failed");
  return _cache(await res.json());
}

export async function getToken(): Promise<string> {
  if (_token && Date.now() < _tokenExpiry) return _token;
  return _refresh(); // throws if no valid refresh cookie → UI redirects to /login
}

// ── Base request helper ───────────────────────────────────────────────────────

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const token = await getToken();

  const res = await fetch(`${API}${path}`, {
    method,
    headers: {
      ...(body ? { "Content-Type": "application/json" } : {}),
      Authorization: `Bearer ${token}`,
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    _token = null;
    const fresh = await _refresh();
    const retry = await fetch(`${API}${path}`, {
      method,
      headers: {
        ...(body ? { "Content-Type": "application/json" } : {}),
        Authorization: `Bearer ${fresh}`,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!retry.ok) {
      const err = await retry.json().catch(() => ({ detail: retry.statusText }));
      throw new Error(err.detail || `HTTP ${retry.status}`);
    }
    return retry.json() as Promise<T>;
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── API surface ───────────────────────────────────────────────────────────────

export const api = {
  // Auth
  login: async (email: string, password: string): Promise<User> => {
    const res = await fetch(`${API}/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Login failed.");
    }
    const data: TokenPayload = await res.json();
    _cache(data);
    return data.user;
  },

  register: async (name: string, email: string, password: string): Promise<User> => {
    const res = await fetch(`${API}/auth/register`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ name, email, password }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "Registration failed.");
    }
    const data: TokenPayload = await res.json();
    _cache(data);
    return data.user;
  },

  logout: async (): Promise<void> => {
    _token = null;
    _tokenExpiry = 0;
    clearAuth();
    await fetch(`${API}/auth/logout`, {
      method: "POST",
      credentials: "include",
    }).catch(() => {});
  },

  // Patients
  createPatient: (name: string, age: number, gender?: string, phone?: string) =>
    req<Patient>("POST", "/patients", { name, age, gender, phone }),

  listPatients: () => req<{ patients: Patient[] }>("GET", "/patients"),

  getPatient: (patientId: string) =>
    req<Patient>("GET", `/patients/${patientId}`),

  getPatientHistory: (patientId: string) =>
    req<{ patient: Patient; sessions: ConsultationSummary[] }>(
      "GET",
      `/patients/${patientId}/history`
    ),

  updatePatient: (patientId: string, updates: Partial<Pick<Patient, "name" | "age" | "gender" | "phone">>) =>
    req<Patient>("PATCH", `/patients/${patientId}`, updates),

  // Consultations
  startConsultation: (
    specialty: Specialty,
    patientLanguage?: string,
    patientName?: string,
    patientAge?: number,
    patientGender?: string,
    chiefComplaint?: string,
    patientId?: string,
  ) =>
    req<StartResponse>("POST", "/consultation/start", {
      specialty,
      patient_language: patientLanguage || undefined,
      patient_name: patientName || undefined,
      patient_age: patientAge || undefined,
      patient_gender: patientGender || undefined,
      chief_complaint: chiefComplaint || undefined,
      patient_id: patientId || undefined,
    }),

  submitAnswer: (sessionId: string, answer: string) =>
    req<AnswerResponse>("POST", `/consultation/${sessionId}/answer`, { answer }),

  submitAudioAnswer: async (sessionId: string, blob: Blob): Promise<AnswerResponse> => {
    const token = await getToken();
    const form = new FormData();
    form.append("audio_file", blob, "answer.wav");
    const res = await fetch(`${API}/consultation/${sessionId}/answer-audio`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: form,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  getQALog: (sessionId: string) =>
    req<QALogResponse>("GET", `/consultation/${sessionId}/qa-log`),

  editAnswer: (sessionId: string, questionId: string, answer: string) =>
    req<{ ok: boolean }>("PATCH", `/consultation/${sessionId}/answer/${questionId}`, { answer }),

  prescribe: (sessionId: string, confirmedDiagnosis: string) =>
    req<{ prescription: PrescriptionResult }>("POST", `/consultation/${sessionId}/prescribe`, {
      confirmed_diagnosis: confirmedDiagnosis,
    }),

  finalize: (sessionId: string) =>
    req<Record<string, unknown>>("POST", `/consultation/${sessionId}/finalize`),

  submitAnswerStream: (
    sessionId: string,
    answer: string,
    onToken: (text: string) => void,
    onDone: (data: { next_question: string | null; history_complete: boolean; new_flags: unknown[] }) => void,
    onError?: (msg: string) => void,
  ): (() => void) => {
    const ctrl = new AbortController();
    (async () => {
      try {
        const token = await getToken();
        const res = await fetch(`${API}/consultation/${sessionId}/answer-stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
          body: JSON.stringify({ answer }),
          signal: ctrl.signal,
        });
        if (!res.ok || !res.body) { onError?.(`HTTP ${res.status}`); return; }
        const reader = res.body.getReader();
        const dec = new TextDecoder();
        let buf = "";
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += dec.decode(value, { stream: true });
          const lines = buf.split("\n");
          buf = lines.pop() ?? "";
          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const evt = JSON.parse(line.slice(6));
            if (evt.event === "token") onToken(evt.text ?? "");
            else if (evt.event === "done") onDone(evt);
            else if (evt.event === "error") onError?.(evt.message ?? "Stream error");
          }
        }
      } catch (e) {
        if ((e as Error).name !== "AbortError") onError?.((e as Error).message);
      }
    })();
    return () => ctrl.abort();
  },

  speak: async (text: string): Promise<string | null> => {
    try {
      const token = await getToken();
      const res = await fetch(`${API}/note/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) return null;
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    } catch {
      return null;
    }
  },

  pipelineUrl: async (sessionId: string): Promise<string> => {
    const token = await getToken();
    return `${API}/consultation/${sessionId}/pipeline?token=${token}`;
  },

  voiceStreamUrl: async (sessionId: string): Promise<string> => {
    const token = await getToken();
    const wsBase = BASE.replace(/^http/, "ws");
    return `${wsBase}/api/v1/consultation/${sessionId}/voice-stream?token=${token}`;
  },
};
