import { useEffect, type ReactNode } from "react";
import type { JobState } from "../api";
import type { HandsFreeState } from "../useHandsFree";
import type { SpeechLang } from "../speechLang";
import { AIOrb, type OrbState } from "./AIOrb";
import { MonitorIcon, PlayPauseIcon, SkipIcon, VolumeIcon } from "./Icons";

interface MicControls {
  state: "idle" | "recording" | "denied" | "unsupported" | "insecure";
  start: () => Promise<void>;
  stop: () => void;
  toggle: () => void;
  volume: number;
  mode: "hold" | "tap";
  setMode: (mode: "hold" | "tap") => void;
}

export type MicMode = "hold" | "tap" | "handsfree";

interface MicrophoneHeroProps {
  mic: MicControls;
  wsUp: boolean;
  pc2Online: boolean | null;
  currentJobState?: JobState;
  currentJobText?: string | null;
  orbState: OrbState;
  handsFree: { on: boolean; state: HandsFreeState; error: string | null };
  micMode: MicMode;
  onMicMode: (m: MicMode) => void;
  speakOn: boolean;
  onToggleSpeak: () => void;
  speechLang: SpeechLang;
  onSpeechLang: (l: SpeechLang) => void;
  /** Right under the status: what you said, a question/approval, or the last result. */
  belowStatus?: ReactNode;
  onExecuteCommand: (command: string) => void;
}

/** Every phrase here is checked against PC1's shortcut parser (see test_quick_actions_parse). */
export const QUICK_ACTIONS = [
  { label: "Volume up", sub: "+20 %", command: "Volume up 20%", icon: VolumeIcon },
  { label: "Play / Pause", sub: "Music & video", command: "Pause the music", icon: PlayPauseIcon },
  { label: "Next song", sub: "Skip track", command: "Next song", icon: SkipIcon },
  { label: "Look at screen", sub: "What's on it?", command: "What's on the screen?", icon: MonitorIcon },
] as const;

const WORKING: JobState[] = ["created", "transcribing", "planning", "routing", "dispatching", "running", "verifying"];

function status(p: MicrophoneHeroProps): { title: string; sub: string; tone: string } {
  const { mic, wsUp, pc2Online, currentJobState: js, handsFree, micMode } = p;
  if (!wsUp) return { title: "Reconnecting to PC1…", sub: "Commands will work again when the link is back", tone: "warn" };
  if (mic.state === "denied") return { title: "Microphone blocked", sub: "Allow the microphone in your browser settings", tone: "error" };
  if (mic.state === "insecure") return { title: "Microphone needs HTTPS", sub: "Open the app from its https:// address", tone: "error" };
  if (mic.state === "unsupported") return { title: "No microphone here", sub: "Type your command below instead", tone: "warn" };
  if (mic.state === "recording") {
    return { title: "Listening…", sub: mic.mode === "hold" ? "Let go when you finish" : "Tap the orb again when you finish", tone: "live" };
  }
  if (js === "clarifying") return { title: "Waiting for your answer", sub: "Answer the question above", tone: "warn" };
  if (js === "awaiting_confirm") return { title: "Waiting for your approval", sub: "Approve or cancel above", tone: "warn" };
  if (js && WORKING.includes(js)) {
    return { title: js === "transcribing" ? "Understanding what you said…" : "Working on it…", sub: "", tone: "busy" };
  }
  if (pc2Online === false) return { title: "PC2 is offline", sub: "Say or type “wake up the PC”", tone: "warn" };
  if (micMode === "handsfree") {
    const hf: Record<HandsFreeState, string> = {
      off: "Hands-free is off", starting: "Starting the microphone…", waiting: "Say “computer, …”",
      hearing: "Hearing you…", sending: "Checking what you said…", armed: "Yes? Say your command", error: "Hands-free stopped",
    };
    return { title: hf[handsFree.state], sub: handsFree.error || "Keep this screen open · other speech is ignored", tone: handsFree.state === "error" ? "error" : "live" };
  }
  return {
    title: "Ready",
    sub: `${micMode === "hold" ? "Hold the orb while you talk" : "Tap the orb, talk, tap again"} · you check it before it runs`,
    tone: "ready",
  };
}

export function MicrophoneHero(props: MicrophoneHeroProps) {
  const { mic, orbState, micMode, onMicMode, speakOn, onToggleSpeak, onExecuteCommand, currentJobText, currentJobState,
    speechLang, onSpeechLang } = props;
  const recording = mic.state === "recording";
  const micUsable = mic.state === "idle" || recording;
  const s = status(props);
  const working = !!currentJobState && WORKING.includes(currentJobState);

  // Desktop: hold Space to talk (hold mode only, never while typing)
  useEffect(() => {
    if (micMode !== "hold") return;
    const typing = () => {
      const a = document.activeElement;
      return a instanceof HTMLInputElement || a instanceof HTMLTextAreaElement;
    };
    const down = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat && !typing() && mic.state === "idle") {
        e.preventDefault();
        void mic.start();
      }
    };
    const up = (e: KeyboardEvent) => {
      if (e.code === "Space" && !typing() && mic.state === "recording") {
        e.preventDefault();
        mic.stop();
      }
    };
    window.addEventListener("keydown", down);
    window.addEventListener("keyup", up);
    return () => {
      window.removeEventListener("keydown", down);
      window.removeEventListener("keyup", up);
    };
  }, [mic, micMode]);

  // The orb IS the microphone (hold or tap). In hands-free mode it just shows the state.
  const orbHandlers =
    micMode === "handsfree" || !micUsable
      ? {}
      : micMode === "hold"
        ? {
            onPointerDown: (e: React.PointerEvent) => {
              e.preventDefault();
              // Keep the pointer even if the finger slides off the orb: sliding used to cut the recording short
              try {
                e.currentTarget.setPointerCapture(e.pointerId);
              } catch {
                /* older browsers: still works while the finger stays on the orb */
              }
              void mic.start();
            },
            onPointerUp: mic.stop,
            onPointerCancel: mic.stop,
          }
        : { onClick: mic.toggle };

  return (
    <div className={`voice-hero orb-state-${orbState} ${recording ? "is-recording" : ""}`}>
      <div className="hero-orb-wrap" onContextMenu={(e) => e.preventDefault()}>
        <AIOrb state={orbState} volume={mic.volume} interactive={micMode !== "handsfree" && micUsable} {...orbHandlers} />
      </div>

      <div className="hero-status-block" aria-live="polite">
        <div className={`hero-status-pill tone-${s.tone}`}>
          <span className="pulse-indicator" />
          <span>{s.title}</span>
        </div>
        {working && currentJobText ? (
          <p className="hero-status-sub hero-job-text">“{currentJobText}”</p>
        ) : (
          s.sub && <p className="hero-status-sub">{s.sub}</p>
        )}
      </div>

      {props.belowStatus && <div className="hero-slot">{props.belowStatus}</div>}

      <div className="mic-mode-row">
        <div className="mode-switch-group" role="radiogroup" aria-label="How to use the microphone">
          {(
            [
              ["hold", "Hold to talk"],
              ["tap", "Tap to talk"],
              ["handsfree", "Hands-free"],
            ] as const
          ).map(([m, label]) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={micMode === m}
              className={`mode-pill ${micMode === m ? "active" : ""}`}
              onClick={() => onMicMode(m)}
            >
              {label}
            </button>
          ))}
        </div>
        <div className="mode-switch-group lang-switch" role="radiogroup" aria-label="Language you speak">
          {(
            [
              ["en", "English"],
              ["th", "ไทย"],
            ] as const
          ).map(([l, label]) => (
            <button
              key={l}
              type="button"
              role="radio"
              aria-checked={speechLang === l}
              className={`mode-pill ${speechLang === l ? "active" : ""}`}
              onClick={() => onSpeechLang(l)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="speak-toggle">
          <input type="checkbox" role="switch" checked={speakOn} onChange={onToggleSpeak} />
          <span>Speak results aloud</span>
        </label>
      </div>

      <div className="hud-quick-controls" aria-label="Quick actions">
        {QUICK_ACTIONS.map(({ label, sub, command, icon: Icon }) => (
          <button key={label} type="button" className="hud-card" onClick={() => onExecuteCommand(command)} title={command}>
            <div className="hud-card-icon-wrap">
              <Icon size={18} />
            </div>
            <div className="hud-card-info">
              <span className="hud-card-title">{label}</span>
              <span className="hud-card-sub">{sub}</span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
