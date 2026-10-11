import type { CSSProperties } from "react";

export type OrbState = "idle" | "listening" | "processing" | "executing" | "success" | "error" | "offline";

interface AIOrbProps {
  state: OrbState;
  /** Microphone input volume 0–1, drives reactive animation in the 'listening' state. */
  volume?: number;
  interactive?: boolean;
  onClick?: () => void;
  onPointerDown?: (e: React.PointerEvent) => void;
  onPointerUp?: () => void;
  onPointerLeave?: () => void;
  onPointerCancel?: () => void;
}

/**
 * Cyber Minimal HUD — Holographic AI Living Energy Orb.
 *
 * State-driven CSS controls:
 * - Concentric acoustic ripple waves radiating outward
 * - Crystalline holographic sphere with liquid caustic refraction core
 * - Fine HUD telemetry arc ring
 * - Dynamic volume reactivity scaling inner energy & acoustic ripples
 */
export function AIOrb({
  state,
  volume = 0,
  interactive = false,
  onClick,
  onPointerDown,
  onPointerUp,
  onPointerLeave,
  onPointerCancel,
}: AIOrbProps) {
  return (
    <div
      className={`ai-orb orb-${state} ${interactive ? "is-interactive" : ""}`}
      style={{ "--orb-volume": volume } as CSSProperties}
      role={interactive ? "button" : "img"}
      tabIndex={interactive ? 0 : undefined}
      aria-label={`AI assistant: ${state}`}
      onClick={onClick}
      onPointerDown={onPointerDown}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerLeave}
      onPointerCancel={onPointerCancel}
    >
      {/* Concentric Acoustic Ripple Waves */}
      <div className="orb-ripples" aria-hidden="true">
        <span className="orb-ripple-ring r1" />
        <span className="orb-ripple-ring r2" />
        <span className="orb-ripple-ring r3" />
      </div>

      {/* Cyber HUD Telemetry Ring */}
      <div className="orb-hud-ring" aria-hidden="true">
        <svg viewBox="0 0 220 220" className="orb-hud-svg">
          <circle cx="110" cy="110" r="104" className="hud-track" />
          <circle cx="110" cy="110" r="104" className="hud-arc arc-1" />
          <circle cx="110" cy="110" r="96" className="hud-ticks" strokeDasharray="2, 8" />
        </svg>
      </div>

      {/* Deep Ambient Neon Halo Glow */}
      <div className="orb-ambient-glow" aria-hidden="true" />

      {/* Crystalline Holographic 3D Sphere */}
      <div className="orb-holo-sphere" aria-hidden="true">
        {/* Liquid Caustic Wave Core */}
        <div className="orb-wave-caustic" />
        {/* Luminous Inner Plasma Center */}
        <div className="orb-plasma-core" />
        {/* Glass Edge Refraction Rim */}
        <div className="orb-glass-rim" />
        {/* Specular Caustic Glint */}
        <div className="orb-glass-glint" />
      </div>

      {/* Success checkmark overlay */}
      {state === "success" && (
        <div className="orb-state-overlay orb-success-check" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="38" height="38" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </div>
      )}

      {/* Offline / Standby indicator */}
      {state === "offline" && (
        <div className="orb-state-overlay orb-offline-indicator" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="28" height="28" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <line x1="1" y1="1" x2="23" y2="23" />
            <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
            <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
            <path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
            <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
            <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
            <line x1="12" y1="20" x2="12.01" y2="20" />
          </svg>
        </div>
      )}
    </div>
  );
}
