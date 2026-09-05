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

const kioskTokenKey = (slug: string) => `kiosk_token:${slug}`;

export function getKioskToken(slug: string): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(kioskTokenKey(slug));
}

export function setKioskToken(slug: string, token: string): void {
  sessionStorage.setItem(kioskTokenKey(slug), token);
}

export function clearKioskToken(slug: string): void {
  sessionStorage.removeItem(kioskTokenKey(slug));
}

function kioskAuthHeaders(slug: string): HeadersInit {
  const token = getKioskToken(slug);
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseTicketError(res: Response, slug: string): Promise<never> {
  if (res.status === 401 || res.status === 403) {
    clearKioskToken(slug);
    throw new Error("kiosk_locked");
  }
  const err = await res.json().catch(() => ({ detail: res.statusText }));
  const detail = err.detail;
  throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
}

// ── Patient check-in API (kiosk JWT after PIN unlock) ─────────

export const ticketApi = {
  getConfig: async (
    slug: string
  ): Promise<{
    slug: string;
    name: string;
    collect_caste: boolean;
    has_kiosk_pin: boolean;
  }> => {
    const res = await fetch(`${API_V2}/t/${slug}/config`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    return res.json();
  },

  unlock: async (
    slug: string,
    pin: string
  ): Promise<{
    access_token: string;
    expires_in: number;
    hospital_name: string;
    collect_caste: boolean;
  }> => {
    const res = await fetch(`${API_V2}/t/${slug}/unlock`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = err.detail;
      throw new Error(typeof detail === "string" ? detail : `HTTP ${res.status}`);
    }
    const data = await res.json();
    setKioskToken(slug, data.access_token);
    return data;
  },

  /** Create a new ticket session. */
  startSession: async (
    slug: string,
    phone: string,
    language: string,
    visitType: string,
    gender: string,
    caste?: string
  ): Promise<StartSessionResponse> => {
    const res = await fetch(`${API_V2}/t/${slug}/session`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...kioskAuthHeaders(slug) },
      body: JSON.stringify({
        phone,
        language,
        visit_type: visitType,
        gender,
        ...(caste ? { caste } : {}),
      }),
    });
    if (!res.ok) return parseTicketError(res, slug);
    return res.json();
  },

  /** Get session result (summary + flags). */
  getResult: async (
    slug: string,
    sessionId: string
  ): Promise<SessionResultResponse> => {
    const res = await fetch(`${API_V2}/t/${slug}/session/${sessionId}/result`, {
      headers: kioskAuthHeaders(slug),
    });
    if (!res.ok) return parseTicketError(res, slug);
    return res.json();
  },

  /** Soft-delete (discard) a session. */
  discard: async (slug: string, sessionId: string): Promise<void> => {
    const res = await fetch(`${API_V2}/t/${slug}/session/${sessionId}/discard`, {
      method: "POST",
      headers: kioskAuthHeaders(slug),
    });
    if (!res.ok) return parseTicketError(res, slug);
  },

  /** Returns the WS URL for the voice call. */
  voiceWsUrl: (slug: string, sessionId: string): string => {
    const token = getKioskToken(slug) || "";
    return `${WS_BASE}/api/v2/t/${slug}/session/${sessionId}/voice?token=${encodeURIComponent(token)}`;
  },
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

  /** The hospital scoped to the caller (hospital_admin via JWT, super_admin via hospital_id). */
  getCurrentHospital: (token: string, hospital_id?: string | null) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<Hospital>("GET", `/hospital${q}`, token);
  },

  createHospital: (
    token: string,
    data: { slug: string; name: string; default_language?: string; kiosk_pin?: string }
  ) => adminReq<Hospital>("POST", "/hospitals", token, data),

  setKioskPin: (token: string, pin: string, hospital_id?: string | null) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<{ ok: boolean; has_kiosk_pin: boolean }>(
      "PATCH",
      `/hospital/pin${q}`,
      token,
      { pin }
    );
  },

  setHospitalSettings: (
    token: string,
    data: { collect_caste: boolean },
    hospital_id?: string | null
  ) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<Hospital>("PATCH", `/hospital/settings${q}`, token, data);
  },

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
      phone?: string;
      date_from?: string;
      date_to?: string;
    },
    hospital_id?: string | null
  ) => {
    const qs = new URLSearchParams();
    if (params?.status) qs.set("status", params.status);
    if (params?.category) qs.set("category", params.category);
    if (params?.include_deleted) qs.set("include_deleted", "true");
    if (params?.limit) qs.set("limit", String(params.limit));
    if (params?.ticket) qs.set("ticket", params.ticket);
    if (params?.phone) qs.set("phone", params.phone);
    if (params?.date_from) qs.set("date_from", params.date_from);
    if (params?.date_to) qs.set("date_to", params.date_to);
    if (hospital_id) qs.set("hospital_id", hospital_id);
    const q = qs.toString();
    return adminReq<{ sessions: AdminSession[]; count: number }>(
      "GET",
      `/sessions${q ? `?${q}` : ""}`,
      token
    );
  },

  getSession: (token: string, sessionId: string, hospital_id?: string | null) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<AdminSession & { qa_log: unknown[]; summary: unknown; patient: unknown }>(
      "GET",
      `/sessions/${sessionId}${q}`,
      token
    );
  },

  listCategories: (token: string, include_inactive?: boolean, hospital_id?: string | null) => {
    const qs = new URLSearchParams();
    if (include_inactive) qs.set("include_inactive", "true");
    if (hospital_id) qs.set("hospital_id", hospital_id);
    const q = qs.toString();
    return adminReq<{ categories: TicketCategory[] }>(
      "GET",
      `/categories${q ? `?${q}` : ""}`,
      token
    );
  },

  createCategory: (token: string, data: { key: string; label: string }, hospital_id?: string | null) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<TicketCategory>("POST", `/categories${q}`, token, data);
  },

  updateCategory: (
    token: string,
    categoryId: string,
    data: { label?: string; active?: boolean },
    hospital_id?: string | null
  ) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<TicketCategory>("PATCH", `/categories/${categoryId}${q}`, token, data);
  },

  listAdminUsers: (token: string, hospital_id?: string) => {
    const q = hospital_id ? `?hospital_id=${hospital_id}` : "";
    return adminReq<{ users: Array<{ email: string; name: string; role: string; hospital_id?: string }> }>(
      "GET", `/users${q}`, token
    );
  },

  createAdminUser: (
    token: string,
    data: {
      email: string;
      name: string;
      password: string;
      role: "hospital_admin" | "super_admin" | "doctor";
      hospital_id?: string;
    }
  ) => adminReq<{ id: string; email: string; name: string; role: string }>(
    "POST", "/users", token, data
  ),
};

// ── WebSocket voice helper ────────────────────────────────────

const TARGET_CAPTURE_HZ = 16000;
const AGENT_PCM_HZ = 24000;
const DUCK_RMS = 0.02;

function downsampleToPcm16(float32: Float32Array, fromRate: number, toRate: number): Int16Array {
  if (fromRate === toRate) {
    const out = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      out[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768));
    }
    return out;
  }
  const ratio = fromRate / toRate;
  const newLen = Math.floor(float32.length / ratio);
  const out = new Int16Array(newLen);
  for (let i = 0; i < newLen; i++) {
    out[i] = Math.max(-32768, Math.min(32767, float32[Math.floor(i * ratio)] * 32768));
  }
  return out;
}

function floatRms(samples: Float32Array): number {
  if (samples.length === 0) return 0;
  let acc = 0;
  for (let i = 0; i < samples.length; i++) acc += samples[i] * samples[i];
  return Math.sqrt(acc / samples.length);
}

function decodeBase64Pcm16(b64: string): Int16Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Int16Array(bytes.buffer, bytes.byteOffset, Math.floor(bytes.byteLength / 2));
}

export class TicketVoiceWS {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private silentGain: GainNode | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private micOpen = false;
  private voiceMode: "legacy" | "gemini_live" = "legacy";
  private agentPlaying = false;
  private pcmSources: AudioBufferSourceNode[] = [];
  private pcmNextTime = 0;
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

    if (msg.type === "ready") {
      if (msg.voice_mode === "gemini_live") {
        this.voiceMode = "gemini_live";
        this.micOpen = true;
        this.onMicOpen();
        void this._openMic();
      }
      this.onEvent(msg);
      return;
    }

    if (msg.type === "agent_speaking") {
      if (this.voiceMode === "gemini_live") {
        this.onEvent(msg);
      } else {
        this.stopMic();
        this.onAudio(msg.question, msg.audio_b64);
      }
      return;
    }

    if (msg.type === "agent_done_speaking") {
      if (this.voiceMode === "gemini_live") {
        this.agentPlaying = false;
        this.onEvent(msg);
      } else {
        this.micOpen = true;
        this.onMicOpen();
        void this._openMic();
      }
      return;
    }

    if (msg.type === "agent_audio_chunk") {
      this.agentPlaying = true;
      this._playPcmChunk(msg.audio_b64);
      this.onEvent(msg);
      return;
    }

    if (msg.type === "interrupt") {
      this._interruptPcm();
      this.agentPlaying = false;
      this.onEvent(msg);
      return;
    }

    if (msg.type === "category_manual_required") {
      this.micOpen = false;
      this._interruptPcm();
      this.agentPlaying = false;
      this.onEvent(msg);
      return;
    }

    if (msg.type === "consultation_started" && this.voiceMode === "gemini_live") {
      this.micOpen = true;
      this.onMicOpen();
      this.onEvent(msg);
      return;
    }

    this.onEvent(msg);
  }

  private async _openMic(): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      if (!this.micStream) {
        const gemini = this.voiceMode === "gemini_live";
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: gemini
            ? {
                echoCancellation: true,
                noiseSuppression: true,
                autoGainControl: true,
                channelCount: 1,
              }
            : { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
      }
      if (!this.audioCtx) {
        this.audioCtx =
          this.voiceMode === "gemini_live"
            ? new AudioContext()
            : new AudioContext({ sampleRate: 16000 });
      }
      if (this.audioCtx.state === "suspended") {
        await this.audioCtx.resume();
      }
      if (this.processor) return;

      this.micSource = this.audioCtx.createMediaStreamSource(this.micStream);
      // ScriptProcessor for broad browser compat; 4096 frames ≈ 256ms at 16kHz
      this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.micOpen || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        const float32 = e.inputBuffer.getChannelData(0);
        if (
          this.voiceMode === "gemini_live" &&
          this.agentPlaying &&
          floatRms(float32) < DUCK_RMS
        ) {
          return;
        }
        const fromRate = this.audioCtx?.sampleRate ?? TARGET_CAPTURE_HZ;
        const pcm16 = downsampleToPcm16(float32, fromRate, TARGET_CAPTURE_HZ);
        this.ws.send(pcm16.buffer);
      };
      this.micSource.connect(this.processor);
      this.silentGain = this.audioCtx.createGain();
      this.silentGain.gain.value = 0;
      this.processor.connect(this.silentGain);
      this.silentGain.connect(this.audioCtx.destination);
    } catch (err) {
      console.error("Mic access failed:", err);
    }
  }

  private _playPcmChunk(b64: string): void {
    if (!this.audioCtx || this.voiceMode !== "gemini_live") return;
    const pcm16 = decodeBase64Pcm16(b64);
    if (pcm16.length === 0) return;
    const ctx = this.audioCtx;
    const ratio = ctx.sampleRate / AGENT_PCM_HZ;
    const outLen = Math.max(1, Math.floor(pcm16.length * ratio));
    const buffer = ctx.createBuffer(1, outLen, ctx.sampleRate);
    const data = buffer.getChannelData(0);
    const last = pcm16.length - 1;
    for (let i = 0; i < outLen; i++) {
      const src = i / ratio;
      const i0 = Math.min(Math.floor(src), last);
      const i1 = Math.min(i0 + 1, last);
      const frac = src - i0;
      data[i] = (pcm16[i0] / 32768) * (1 - frac) + (pcm16[i1] / 32768) * frac;
    }
    const src = ctx.createBufferSource();
    src.buffer = buffer;
    src.connect(ctx.destination);
    const now = ctx.currentTime;
    if (this.pcmNextTime < now) this.pcmNextTime = now;
    src.start(this.pcmNextTime);
    this.pcmNextTime += buffer.duration;
    this.pcmSources.push(src);
    src.onended = () => {
      this.pcmSources = this.pcmSources.filter((s) => s !== src);
    };
  }

  private _interruptPcm(): void {
    for (const src of this.pcmSources) {
      try {
        src.stop();
      } catch {
        /* already stopped */
      }
    }
    this.pcmSources = [];
    if (this.audioCtx) this.pcmNextTime = this.audioCtx.currentTime;
  }

  stopMic(): void {
    this.micOpen = false;
    if (this.voiceMode === "gemini_live") {
      // Keep the capture graph running so barge-in stays possible; just stop sending.
      return;
    }
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
  }

  sendCategorySelected(key: string, label: string): void {
    this.ws?.send(JSON.stringify({ type: "category_selected", key, label }));
  }

  stop(): void {
    this.micOpen = false;
    this._interruptPcm();
    this.ws?.send(JSON.stringify({ type: "stop" }));
    if (this.processor) {
      this.processor.disconnect();
      this.processor = null;
    }
    if (this.micSource) {
      this.micSource.disconnect();
      this.micSource = null;
    }
    if (this.silentGain) {
      this.silentGain.disconnect();
      this.silentGain = null;
    }
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
