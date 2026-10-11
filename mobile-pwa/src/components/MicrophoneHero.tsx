import { useEffect } from "react";
import type { JobState } from "../api";
import { MicIcon, MicOffIcon, SparklesIcon, WifiOffIcon } from "./Icons";
import { AudioWaveform } from "./AudioWaveform";

interface MicControls {
  state: "idle" | "recording" | "denied" | "unsupported" | "insecure";
  start: () => Promise<void>;
  stop: () => void;
  toggle: () => void;
  volume: number;
  mode: "hold" | "tap";
  setMode: (mode: "hold" | "tap") => void;
}

interface MicrophoneHeroProps {
  mic: MicControls;
  wsUp: boolean;
  pc2Online: boolean | null;
  busy: boolean;
  currentJobState?: JobState;
}

export function MicrophoneHero({ mic, wsUp, pc2Online, busy, currentJobState }: MicrophoneHeroProps) {
  const isRecording = mic.state === "recording";
  const isProcessing =
    currentJobState === "transcribing" ||
    currentJobState === "planning" ||
    currentJobState === "routing" ||
    currentJobState === "dispatching" ||
    currentJobState === "running" ||
    currentJobState === "verifying";

  // Keyboard shortcut: Spacebar to talk when not focused on an input/textarea
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.code === "Space" && !e.repeat) {
        const active = document.activeElement;
        const isInputField = active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement;
        if (!isInputField && mic.state === "idle") {
          e.preventDefault();
          if (mic.mode === "hold") {
            void mic.start();
          } else {
            mic.toggle();
          }
        }
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.code === "Space") {
        const active = document.activeElement;
        const isInputField = active instanceof HTMLInputElement || active instanceof HTMLTextAreaElement;
        if (!isInputField && mic.mode === "hold" && mic.state === "recording") {
          e.preventDefault();
          mic.stop();
        }
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, [mic]);

  let statusBadge = "Ready — speak English";
  let statusBadgeClass = "badge-ready";
  if (!wsUp) {
    statusBadge = "Connecting to PC1…";
    statusBadgeClass = "badge-connecting";
  } else if (pc2Online === false) {
    statusBadge = "PC2 offline (waiting for the PC)";
    statusBadgeClass = "badge-offline";
  } else if (isRecording) {
    statusBadge = "Listening…";
    statusBadgeClass = "badge-listening";
  } else if (currentJobState === "transcribing") {
    statusBadge = "Transcribing…";
    statusBadgeClass = "badge-processing";
  } else if (currentJobState === "planning") {
    statusBadge = "Planning…";
    statusBadgeClass = "badge-processing";
  } else if (currentJobState === "awaiting_confirm") {
    statusBadge = "Waiting for your confirmation";
    statusBadgeClass = "badge-warning";
  } else if (busy) {
    statusBadge = "PC is working…";
    statusBadgeClass = "badge-processing";
  }

  return (
    <div className={`voice-hero ${isRecording ? "is-recording" : ""} ${isProcessing ? "is-processing" : ""}`}>
      {/* State Badge */}
      <div className="voice-status-wrap">
        <span className={`voice-status-badge ${statusBadgeClass}`}>
          {isRecording ? (
            <span className="pulse-indicator red" />
          ) : isProcessing ? (
            <SparklesIcon size={14} className="spin-slow" />
          ) : !wsUp ? (
            <WifiOffIcon size={14} />
          ) : (
            <span className="pulse-indicator cyan" />
          )}
          <span>{statusBadge}</span>
        </span>
      </div>

      {/* Center Interactive Orb & Button */}
      <div className="voice-orb-container">
        <div className={`glow-ring ring-1 ${isRecording ? "active" : ""}`} />
        <div className={`glow-ring ring-2 ${isRecording ? "active" : ""}`} />

        <button
          type="button"
          className={`mic-primary-button ${isRecording ? "recording" : ""}`}
          disabled={mic.state === "insecure" || mic.state === "unsupported"}
          aria-label={
            isRecording
              ? mic.mode === "hold"
                ? "Release to send"
                : "Tap to send"
              : mic.mode === "hold"
              ? "Hold and speak English"
              : "Tap and speak English"
          }
          {...(mic.mode === "hold"
            ? {
                onPointerDown: (e) => {
                  e.preventDefault();
                  void mic.start();
                },
                onPointerUp: mic.stop,
                onPointerLeave: mic.stop,
                onPointerCancel: mic.stop,
              }
            : {
                onClick: mic.toggle,
              })}
          onContextMenu={(e) => e.preventDefault()}
        >
          <div className="mic-icon-wrapper">
            {mic.state === "denied" || mic.state === "unsupported" || mic.state === "insecure" ? (
              <MicOffIcon size={44} />
            ) : (
              <MicIcon size={48} className={isRecording ? "mic-active-svg" : ""} />
            )}
          </div>

          <span className="mic-action-label">
            {isRecording
              ? mic.mode === "hold"
                ? "Release to send"
                : "Tap to send"
              : mic.mode === "hold"
              ? "Hold to talk"
              : "Tap to talk"}
          </span>
        </button>
      </div>

      {/* Audio Waveform visualization */}
      <div className="voice-waveform-section">
        <AudioWaveform isRecording={isRecording} volume={mic.volume} isProcessing={isProcessing} />
      </div>

      {/* Mode Switcher and Desktop Shortcut Hint */}
      <div className="voice-footer-meta">
        <div className="mode-switch-group">
          <button
            type="button"
            className={`mode-pill ${mic.mode === "hold" ? "active" : ""}`}
            onClick={() => mic.setMode("hold")}
            title="Hold while speaking, release to send"
          >
            Hold to talk
          </button>
          <button
            type="button"
            className={`mode-pill ${mic.mode === "tap" ? "active" : ""}`}
            onClick={() => mic.setMode("tap")}
            title="Tap once to start, tap again to send"
          >
            Tap to toggle
          </button>
        </div>
        <p className="shortcut-hint">You can also hold the Spacebar to talk</p>
      </div>

      {/* Error & Warning Diagnostic Hints */}
      {mic.state === "denied" && (
        <div className="hint-card hint-error">
          <strong>Microphone access was denied</strong>
          <p>Tap the lock/settings icon in the address bar and allow the microphone, or type your command below.</p>
        </div>
      )}
      {mic.state === "insecure" && (
        <div className="hint-card hint-warn">
          <strong>Microphone needs HTTPS</strong>
          <p>Browsers only allow the microphone over HTTPS. Open the https:// address of this app, or type your command.</p>
        </div>
      )}
      {mic.state === "unsupported" && (
        <div className="hint-card hint-info">
          <strong>This browser cannot record audio</strong>
          <p>Type your command in the box below instead.</p>
        </div>
      )}
    </div>
  );
}
