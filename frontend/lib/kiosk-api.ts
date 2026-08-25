"use client";
import type {
  GrievanceResultResponse,
  KioskWSEvent,
  StartSessionResponse,
} from "./kiosk-types";

const BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
const API_V2 = `${BASE}/api/v2`;
const WS_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8001")
  .replace(/^http/, "ws");

export const kioskApi = {
  startSession: async (
    slug: string,
    phone: string,
    language: string,
    gender: string
  ): Promise<StartSessionResponse> => {
    const res = await fetch(`${API_V2}/kiosk/${slug}/session`, {
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

  getResult: async (slug: string, sessionId: string): Promise<GrievanceResultResponse> => {
    const res = await fetch(`${API_V2}/kiosk/${slug}/session/${sessionId}/result`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    return res.json();
  },

  discard: async (slug: string, sessionId: string): Promise<void> => {
    await fetch(`${API_V2}/kiosk/${slug}/session/${sessionId}/discard`, {
      method: "POST",
    });
  },

  voiceWsUrl: (slug: string, sessionId: string): string =>
    `${WS_BASE}/api/v2/kiosk/${slug}/session/${sessionId}/voice`,
};

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

export class KioskVoiceWS {
  private ws: WebSocket | null = null;
  private audioCtx: AudioContext | null = null;
  private micStream: MediaStream | null = null;
  private processor: ScriptProcessorNode | null = null;
  private silentGain: GainNode | null = null;
  private micSource: MediaStreamAudioSourceNode | null = null;
  private micOpen = false;
  private agentPlaying = false;
  private pcmSources: AudioBufferSourceNode[] = [];
  private pcmNextTime = 0;
  private onEvent: (e: KioskWSEvent) => void;
  private onMicOpen: () => void;

  constructor(opts: {
    onEvent: (e: KioskWSEvent) => void;
    onMicOpen: () => void;
  }) {
    this.onEvent = opts.onEvent;
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

    this.ws.send(JSON.stringify({ type: "start" }));
  }

  private _handleMessage(evt: MessageEvent) {
    if (typeof evt.data !== "string") return;
    let msg: KioskWSEvent;
    try {
      msg = JSON.parse(evt.data);
    } catch {
      return;
    }

    if (msg.type === "ready") {
      this.micOpen = true;
      this.onMicOpen();
      void this._openMic();
      this.onEvent(msg);
      return;
    }

    if (msg.type === "agent_speaking") {
      this.onEvent(msg);
      return;
    }

    if (msg.type === "agent_done_speaking") {
      this.agentPlaying = false;
      this.onEvent(msg);
      return;
    }

    if (msg.type === "agent_audio_chunk") {
      this.agentPlaying = true;
      this._playPcmChunk(msg.audio_b64!);
      this.onEvent(msg);
      return;
    }

    if (msg.type === "interrupt") {
      this._interruptPcm();
      this.agentPlaying = false;
      this.onEvent(msg);
      return;
    }

    this.onEvent(msg);
  }

  private async _openMic(): Promise<void> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      if (!this.micStream) {
        this.micStream = await navigator.mediaDevices.getUserMedia({
          audio: {
            echoCancellation: true,
            noiseSuppression: true,
            autoGainControl: true,
            channelCount: 1,
          },
        });
      }
      if (!this.audioCtx) {
        this.audioCtx = new AudioContext();
      }
      if (this.audioCtx.state === "suspended") {
        await this.audioCtx.resume();
      }
      if (this.processor) return;

      this.micSource = this.audioCtx.createMediaStreamSource(this.micStream);
      this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        if (!this.micOpen || !this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        const float32 = e.inputBuffer.getChannelData(0);
        if (this.agentPlaying && floatRms(float32) < DUCK_RMS) return;
        const fromRate = this.audioCtx?.sampleRate ?? TARGET_CAPTURE_HZ;
        const pcm16 = downsampleToPcm16(float32, fromRate, TARGET_CAPTURE_HZ);
        this.ws.send(pcm16.buffer);
      };
      this.silentGain = this.audioCtx.createGain();
      this.silentGain.gain.value = 0;
      this.micSource.connect(this.processor);
      this.processor.connect(this.silentGain);
      this.silentGain.connect(this.audioCtx.destination);
    } catch {
      /* mic denied */
    }
  }

  private _playPcmChunk(b64: string): void {
    if (!this.audioCtx) return;
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
}
