"use client";
import { useEffect, useRef } from "react";
import clsx from "clsx";

interface Props {
  speaking: boolean;
  loading?: boolean;
  size?: "sm" | "md" | "lg";
}

const SIZES = {
  sm: { wrap: "w-14 h-14", orb: "w-14 h-14", icon: "text-2xl" },
  md: { wrap: "w-20 h-20", orb: "w-20 h-20", icon: "text-3xl" },
  lg: { wrap: "w-28 h-28", orb: "w-28 h-28", icon: "text-4xl" },
};

export default function AIAvatar({ speaking, loading, size = "lg" }: Props) {
  const sz = SIZES[size];

  return (
    <div className={clsx("relative flex items-center justify-center", sz.wrap)}>
      {speaking && (
        <>
          <div className="absolute inset-0 rounded-full shimmer-bg opacity-25 ring-1" />
          <div className="absolute inset-0 rounded-full shimmer-bg opacity-15 ring-2" />
          <div className="absolute inset-0 rounded-full shimmer-bg opacity-10 ring-3" />
        </>
      )}

      <div
        className={clsx(
          sz.orb,
          "rounded-full shimmer-bg shadow-2xl shadow-indigo-500/40",
          "flex items-center justify-center relative overflow-hidden",
          "transition-all duration-300 cursor-default select-none",
          speaking ? "orb-speak" : loading ? "animate-pulse" : "orb-breathe"
        )}
      >
        <div className="absolute inset-0 rounded-full bg-gradient-to-br from-white/25 via-transparent to-transparent pointer-events-none" />
        <div className="absolute bottom-0 left-0 right-0 h-1/3 rounded-b-full bg-black/10 pointer-events-none" />
        <span className={clsx(sz.icon, "relative z-10 drop-shadow-sm")}>⚕️</span>
      </div>

      <span
        className={clsx(
          "absolute bottom-0.5 right-0.5 w-3.5 h-3.5 rounded-full border-2 border-white shadow",
          speaking ? "bg-green-400 animate-pulse" : loading ? "bg-amber-400 animate-pulse" : "bg-slate-300"
        )}
      />
    </div>
  );
}

// Siri/Jarvis-style canvas waveform for AI speaking
export function SiriWaveform({ active }: { active: boolean }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // Mutable ref shared between the RAF loop and active-sync effect
  const stateRef = useRef({ active, amps: [2, 1.5, 2.5] });

  useEffect(() => {
    stateRef.current.active = active;
  }, [active]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const W = 280, H = 56;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.scale(dpr, dpr);

    const CY = H / 2;
    let startTime = 0;
    let rafId = 0;

    const WAVES = [
      { color: "#4f46e5", alpha: 0.9,  phase: 0,             fq: 1.2 },
      { color: "#7c3aed", alpha: 0.65, phase: Math.PI / 2.5, fq: 2.1 },
      { color: "#06b6d4", alpha: 0.5,  phase: Math.PI * 0.7, fq: 0.85 },
    ];
    const AMP_ACTIVE = [18, 12, 22];
    const AMP_IDLE   = [2, 1.5, 2.5];

    const draw = (ts: number) => {
      if (!startTime) startTime = ts;
      const t = (ts - startTime) / 1000;
      const { active: isActive, amps } = stateRef.current;
      const target = isActive ? AMP_ACTIVE : AMP_IDLE;

      // Lerp amplitude toward target for smooth transitions
      for (let i = 0; i < amps.length; i++) {
        amps[i] += (target[i] - amps[i]) * 0.06;
      }

      ctx.clearRect(0, 0, W, H);
      const speed = t * (isActive ? 2.4 : 0.4);

      WAVES.forEach((w, wi) => {
        ctx.beginPath();
        ctx.strokeStyle = w.color;
        ctx.lineWidth = 2;
        ctx.globalAlpha = isActive ? w.alpha : w.alpha * 0.35;
        ctx.lineJoin = "round";

        for (let x = 0; x <= W; x++) {
          const nx = (x / W) * Math.PI * 4 * w.fq;
          const y = CY + Math.sin(nx + w.phase + speed) * amps[wi];
          x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        ctx.stroke();
      });

      ctx.globalAlpha = 1;
      rafId = requestAnimationFrame(draw);
    };

    rafId = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(rafId);
  }, []); // runs once; active changes flow through stateRef

  return (
    <canvas
      ref={canvasRef}
      style={{ width: "280px", height: "56px", display: "block" }}
    />
  );
}

// Legacy CSS bars kept for any other consumers
export function WaveformBars({ active }: { active: boolean }) {
  if (!active) {
    return (
      <div className="flex gap-[5px] items-center h-8">
        {[0, 1, 2, 3, 4].map((i) => (
          <div key={i} className="w-[4px] h-[4px] rounded-full bg-slate-300" />
        ))}
      </div>
    );
  }
  return (
    <div className="flex gap-[5px] items-center h-8">
      {(["bar-1", "bar-2", "bar-3", "bar-4", "bar-5"] as const).map((cls) => (
        <div key={cls} className={clsx("w-[4px] rounded-full shimmer-bg", cls)} />
      ))}
    </div>
  );
}
