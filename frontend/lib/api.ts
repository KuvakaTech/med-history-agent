import type {
  AnswerResponse,
  PrescriptionResult,
  QALogResponse,
  Specialty,
  StartResponse,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8001";
const API = `${BASE}/api/v1`;

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API}${path}`, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  startConsultation: (
    specialty: Specialty,
    patientLanguage?: string,
    patientName?: string,
    patientAge?: number,
    patientGender?: string,
    chiefComplaint?: string,
  ) =>
    req<StartResponse>("POST", "/consultation/start", {
      specialty,
      patient_language: patientLanguage || undefined,
      patient_name: patientName || undefined,
      patient_age: patientAge || undefined,
      patient_gender: patientGender || undefined,
      chief_complaint: chiefComplaint || undefined,
    }),

  submitAnswer: (sessionId: string, answer: string) =>
    req<AnswerResponse>("POST", `/consultation/${sessionId}/answer`, { answer }),

  submitAudioAnswer: async (sessionId: string, blob: Blob): Promise<AnswerResponse> => {
    const form = new FormData();
    form.append("audio_file", blob, "answer.wav");
    const res = await fetch(`${API}/consultation/${sessionId}/answer-audio`, {
      method: "POST",
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
        const res = await fetch(`${API}/consultation/${sessionId}/answer-stream`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
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
      const res = await fetch(`${API}/note/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      if (!res.ok) return null;
      const blob = await res.blob();
      return URL.createObjectURL(blob);
    } catch {
      return null;
    }
  },

  pipelineUrl: (sessionId: string) =>
    `${API}/consultation/${sessionId}/pipeline`,

  voiceStreamUrl: (sessionId: string) =>
    `${BASE.replace(/^http/, "ws")}/api/v1/consultation/${sessionId}/voice-stream`,
};
