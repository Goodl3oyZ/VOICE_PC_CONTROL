import { useEffect } from "react";
import type { JobState } from "../api";
import {
  MicIcon,
  MicOffIcon,
  SparklesIcon,
  WifiOffIcon,
  LaptopIcon,
  VolumeIcon,
  RocketIcon,
  MediaIcon,
  PowerIcon,
} from "./Icons";
import { AudioWaveform } from "./AudioWaveform";
import { AIOrb, type OrbState } from "./AIOrb";
import { TranscriptionPanel } from "./TranscriptionPanel";

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
  orbState: OrbState;
  recentJobText?: string | null;
  onExecuteCommand?: (command: string) => void;
}

export function MicrophoneHero({
  mic,
  wsUp,
  pc2Online,
  currentJobState,
  orbState,
  recentJobText = null,
  onExecuteCommand,
}: MicrophoneHeroProps) {
  const isRecording = mic.state === "recording";
  const isProcessing = orbState === "processing" || orbState === "executing";

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

  // Status headline and subtitle based on orbState & connection
  let statusTitle = "PC CONNECTED • STANDBY";
  let statusSubtitle = "Tap microphone or choose quick actions below";
  let statusBadgeClass = "badge-ready";

  if (!wsUp) {
    statusTitle = "SERVER OFFLINE • RECONNECTING";
    statusSubtitle = "Attempting handshake with PC orchestrator…";
    statusBadgeClass = "badge-connecting";
  } else if (pc2Online === false) {
    statusTitle = "PC AGENT DISCONNECTED";
    statusSubtitle = "Waiting for the PC worker client to link";
    statusBadgeClass = "badge-offline";
  } else if (isRecording) {
    statusTitle = "LISTENING • SPEAK ENGLISH";
    statusSubtitle = mic.mode === "hold" ? "Release button when done speaking" : "Tap again to finish and execute";
    statusBadgeClass = "badge-listening";
  } else if (currentJobState === "transcribing") {
    statusTitle = "TRANSCRIBING SPEECH…";
    statusSubtitle = "Converting voice capture to text with Whisper AI";
    statusBadgeClass = "badge-processing";
  } else if (currentJobState === "planning" || currentJobState === "routing") {
    statusTitle = "ANALYZING COMMAND…";
    statusSubtitle = "AI is generating automated system script";
    statusBadgeClass = "badge-processing";
  } else if (currentJobState === "awaiting_confirm") {
    statusTitle = "CONFIRMATION NEEDED";
    statusSubtitle = "Command requires user authorization";
    statusBadgeClass = "badge-warning";
  } else if (currentJobState === "running" || currentJobState === "dispatching" || currentJobState === "verifying") {
    statusTitle = "CONTROLLING PC…";
    statusSubtitle = "Executing remote automation on Windows";
    statusBadgeClass = "badge-executing";
  } else if (orbState === "success") {
    statusTitle = "COMMAND COMPLETED";
    statusSubtitle = "Action executed successfully on target PC";
    statusBadgeClass = "badge-success";
  } else if (orbState === "error") {
    statusTitle = "EXECUTION FAILED";
    statusSubtitle = "An error occurred during PC automation";
    statusBadgeClass = "badge-error";
  }

  const isButtonDisabled = mic.state === "insecure" || mic.state === "unsupported";

  return (
    <div className={`voice-hero orb-state-${orbState} ${isRecording ? "is-recording" : ""} ${isProcessing ? "is-processing" : ""}`}>
      {/* Living Holographic AI Orb Centerpiece */}
      <div className="hero-orb-wrap">
        <AIOrb state={orbState} volume={mic.volume} />
      </div>

      {/* Cyber HUD Status Badge */}
      <div className="hero-status-block">
        <div className={`hero-status-pill ${statusBadgeClass}`}>
          {isRecording ? (
            <span className="pulse-indicator cyan-pulse" />
          ) : isProcessing ? (
            <SparklesIcon size={14} className="spin-slow" />
          ) : !wsUp ? (
            <WifiOffIcon size={14} />
          ) : pc2Online === false ? (
            <LaptopIcon size={14} />
          ) : (
            <span className="pulse-indicator emerald" />
          )}
          <span>{statusTitle}</span>
        </div>
        <p className="hero-status-sub">{statusSubtitle}</p>
      </div>

      {/* Cyber Minimal HUD Quick Control Cards */}
      <div className="hud-quick-controls" aria-label="PC Quick Controls">
        <button
          type="button"
          className="hud-card"
          onClick={() => onExecuteCommand?.("Volume up 15%")}
          title="Increase Volume"
        >
          <div className="hud-card-icon-wrap volume-icon-glow">
            <VolumeIcon size={18} />
          </div>
          <div className="hud-card-info">
            <span className="hud-card-title">VOLUME</span>
            <span className="hud-card-sub">+15% / Mute</span>
          </div>
        </button>

        <button
          type="button"
          className="hud-card"
          onClick={() => onExecuteCommand?.("Open Google Chrome")}
          title="Launch Chrome"
        >
          <div className="hud-card-icon-wrap app-icon-glow">
            <RocketIcon size={18} />
          </div>
          <div className="hud-card-info">
            <span className="hud-card-title">LAUNCH APP</span>
            <span className="hud-card-sub">Chrome, Spotify</span>
          </div>
        </button>

        <button
          type="button"
          className="hud-card"
          onClick={() => onExecuteCommand?.("Play or pause music")}
          title="Media Control"
        >
          <div className="hud-card-icon-wrap media-icon-glow">
            <MediaIcon size={18} />
          </div>
          <div className="hud-card-info">
            <span className="hud-card-title">MEDIA</span>
            <span className="hud-card-sub">Play / Pause</span>
          </div>
        </button>

        <button
          type="button"
          className="hud-card"
          onClick={() => onExecuteCommand?.("Lock the computer")}
          title="Lock PC"
        >
          <div className="hud-card-icon-wrap power-icon-glow">
            <PowerIcon size={18} />
          </div>
          <div className="hud-card-info">
            <span className="hud-card-title">POWER</span>
            <span className="hud-card-sub">Lock / Sleep</span>
          </div>
        </button>
      </div>

      {/* Live Transcription Panel */}
      <div className="hero-transcription-section">
        <TranscriptionPanel
          jobText={recentJobText}
          isListening={isRecording}
          isProcessing={isProcessing}
        />
      </div>

      {/* Audio Waveform visualization */}
      <div className="voice-waveform-section">
        <AudioWaveform isRecording={isRecording} volume={mic.volume} isProcessing={isProcessing} />
      </div>

      {/* Acoustic Ripple Microphone Trigger (Cyber HUD) */}
      <div className="voice-orb-container">
        <div className="acoustic-ripple-wrapper">
          <div className={`acoustic-ripples ${isRecording ? "active" : ""}`} aria-hidden="true">
            <span className="mic-ripple-ring r1" />
            <span className="mic-ripple-ring r2" />
            <span className="mic-ripple-ring r3" />
          </div>

          <button
            type="button"
            className={`mic-primary-button ${isRecording ? "recording" : ""} ${orbState === "executing" ? "executing" : ""}`}
            disabled={isButtonDisabled}
            aria-label={
              isRecording
                ? mic.mode === "hold"
                  ? "Release to send command"
                  : "Tap to send command"
                : mic.mode === "hold"
                ? "Hold and speak command"
                : "Tap and speak command"
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
                <MicOffIcon size={34} />
              ) : (
                <MicIcon size={36} className={isRecording ? "mic-active-svg" : ""} />
              )}
            </div>

            <span className="mic-action-label">
              {isRecording
                ? mic.mode === "hold"
                  ? "Release to send"
                  : "Tap to send"
                : mic.mode === "hold"
                ? "Hold to talk"
                : "Tap to toggle"}
            </span>
          </button>
        </div>
      </div>

      {/* Mode Switcher and Shortcut Hint */}
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
        <p className="shortcut-hint">Spacebar holds to talk on desktop</p>
      </div>

      {/* Error & Warning Diagnostic Hints */}
      {mic.state === "denied" && (
        <div className="hint-card hint-error">
          <strong>Microphone access was denied</strong>
          <p>Tap the lock/settings icon in your browser address bar and allow microphone permissions.</p>
        </div>
      )}
      {mic.state === "insecure" && (
        <div className="hint-card hint-warn">
          <strong>Microphone requires HTTPS</strong>
          <p>Browsers only permit microphone capture over HTTPS or localhost.</p>
        </div>
      )}
      {mic.state === "unsupported" && (
        <div className="hint-card hint-info">
          <strong>Audio recording unsupported</strong>
          <p>Please enter commands using the text input below.</p>
        </div>
      )}
    </div>
  );
}
