"use client";
import type {
  AdminSession,
  Hospital,
  SessionResultResponse,
  StartSessionResponse,
  TicketCategory,
  TicketWSEvent,
} from "./ticketing-types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const API_V2 = `${BASE}/api/v2`;
const WS_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001")
  .replace(/^http/, "ws");

// ── Public patient API (no auth) ──────────────────────────────

export const ticketApi = {
  /** Create a new ticket session. */
  startSession: async (
    slug: string,
    phone: string,
    language: string,
    gender: string
  ): Promise<StartSessionResponse> => {
    const res = await fetch(`${API_V2}/t/${slug}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ phone, language, gender }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /** Get session result (summary + flags). */
  getResult: async (
    slug: string,
    sessionId: string
  ): Promise<SessionResultResponse> => {
    const res = await fetch(`${API_V2}/t/${slug}/session/${sessionId}/result`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  /** Soft-delete (discard) a session. */
  discard: async (slug: string, sessionId: string): Promise<void> => {
    await fetch(`${API_V2}/t/${slug}/session/${sessionId}/discard`, {
      method: "POST",
    });
  },

  /** Returns the WS URL for the voice call. */
  voiceWsUrl: (slug: string, sessionId: string): string =>
    `${WS_BASE}/api/v2/t/${slug}/session/${sessionId}/voice`,
};

// ── Admin API (requires JWT Bearer) ──────────────────────────

async function adminReq<T>(
  method: string,
  path: string,
  token: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(`${API_V2}/admin${path}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

export const adminApi = {
  listHospitals: (token: string) =>
    adminReq<{ hospitals: Hospital[] }>("GET", "/hospitals", token),

  createHospital: (
    token: string,
    data: { slug: string; name: string; default_language?: string }
  ) => adminReq<Hospital>("POST", "/hospitals", token, data),

  getStats: (token: string, hospital_id?: string) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<{
      date_ist: string;
      today: { total: number; completed: number; partial: number; active: number; critical: number };
      all_time: { total: number; critical: number };
    }>("GET", `/stats${q}`, token);
  },

  listSessions: (
    token: string,
    params?: {
      status?: string;
      category?: string;
      include_deleted?: boolean;
      limit?: number;
      ticket?: string;
      date_from?: string;
      date_to?: string;
    }
  ) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.category) qs.set("category", params.category);
    if (params?.include_deleted) qs.set("include_deleted", "true");
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.ticket) qs.set("ticket", params.ticket);
    if (params?.date_from) qs.set("date_from", params.date_from);
    if (params?.date_to) qs.set("date_to", params.date_to);
    const q = qs.toString();
    return adminReq<{ sessions: AdminSession[]; count: number }>(
      "GET",
      `/sessions${q ? `?${q}` : ""}`,
      token
    );
  },

  getSession: (token: string, sessionId: string) =>
    adminReq<AdminSession & { qa_log: unknown[]; summary: unknown; patient: unknown }>(
      "GET",
      `/sessions/${sessionId}`,
      token
    ),

  listCategories: (token: string, include_inactive?: boolean) =>
    adminReq<{ categories: TicketCategory[] }>(
      "GET",
      `/categories${include_inactive ? "?include_inactive=true" : ""}`,
      token
    ),

  createCategory: (token: string, data: { key: string; label: string }) =>
    adminReq<TicketCategory>("POST", "/categories", token, data),

  updateCategory: (
    token: string,
    categoryId: string,
    data: { label?: string; active?: boolean }
  ) => adminReq<TicketCategory>("PATCH", `/categories/${categoryId}`, token, data),

  listAdminUsers: (token: string, hospital_id?: string) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<{ users: Array<{ email: string; name: string; role: string; hospital_id?: string }> }>(
      "GET", `/users${q}`, token
    );
  },

  createAdminUser: (
    token: string,
    data: { email: string; name: string; password: string; role: "hospital_admin" | "super_admin"; hospital_id?: string }
  ) => adminReq<{ id: string; email: string; name: string; role: string }>(
    "POST", "/users", token, data
  ),
};

// ── WebSocket voice helper ────────────────────────────────────

export class TicketVoiceWS {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private micOpen = false;
  private onEvent: (e: TicketWSEvent) => void;
  private onAudio: (question: string, audioB64: string | null) => void;
  private onMicOpen: () => void;

  constructor(opts: {
    onEvent: (e: TicketWSEvent) => void;
    onAudio: (question: string, audioB64: string | null) => void;
    onMicOpen: () => void;
  }) {
    this.onEvent = opts.onEvent;
    this.onAudio = opts.onAudio;
    this.onMicOpen = opts.onMicOpen;
  }

  async connect(url: string): Promise<void> {
    this.ws = new WebSocket(url);
    this.ws.binaryType = "arraybuffer";

    await new Promise<void>((resolve, reject) => {
      this.ws!.onopen = () => resolve();
      this.ws!.onerror = () => reject(new Error("WebSocket connection failed"));
    });

    this.ws.onmessage = (evt) => this._handleMessage(evt);
    this.ws.onclose = () => {
      this.stopMic();
      this.onEvent({ type: "ended", session_id: "" });
    };

    // Send start handshake
    this.ws.send(JSON.stringify({ type: "start" }));
  }

  private _handleMessage(evt: MessageEvent) {
    if (typeof evt.data !== "string") return;
    let msg: TicketWSEvent;
    try {
      msg = JSON.parse(evt.data);
    } catch {
      return;
    }

    if (msg.type === "agent_speaking") {
      this.stopMic();
      this.onAudio(msg.question, msg.audio_b64);
    } else if (msg.type === "agent_done_speaking") {
      this.micOpen = true;
      this.onMicOpen();
      this._openMic();
    } else {
      this.onEvent(msg);
    }
  }

  private async _openMic(): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      if (!this.micStream) {
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
      }
      if (!this.audioCtx) {
        this.audioCtx = new AudioContext({ sampleRate: 16000 });
      }
      const source = this.audioCtx.createMediaStreamSource(this.micStream);
      // Use ScriptProcessor for broad browser compat; 4096 frames ≈ 256ms at 16kHz
      this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.micOpen || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        const float32 = e.inputBuffer.getChannelData(0);
        const pcm16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i++) {
          pcm16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
        }
        this.ws.send(pcm16.buffer);
      };
      source.connect(this.processor);
      this.processor.connect(this.audioCtx.destination);
    } catch (err) {
      console.error("Mic access failed:", err);
    }
  }

  stopMic(): void {
    this.micOpen = false;
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
  }

  sendCategorySelected(key: string, label: string): void {
    this.ws?.send(JSON.stringify({ type: "category_selected", key, label }));
  }

  stop(): void {
    this.stopMic();
    this.ws?.send(JSON.stringify({ type: "stop" }));
    if (this.micStream) {
      this.micStream.getTracks().forEach((t) => t.stop());
      this.micStream = null;
    }
    if (this.audioCtx) {
      this.audioCtx.close();
      this.audioCtx = null;
    }
    this.ws?.close();
    this.ws = null;
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
