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

  let statusBadge = "พร้อมรับคำสั่งเสียง";
  let statusBadgeClass = "badge-ready";
  if (!wsUp) {
    statusBadge = "กำลังเชื่อมต่อเซิร์ฟเวอร์ PC1…";
    statusBadgeClass = "badge-connecting";
  } else if (pc2Online === false) {
    statusBadge = "PC2 ออฟไลน์ (รอเครื่องปลายทาง)";
    statusBadgeClass = "badge-offline";
  } else if (isRecording) {
    statusBadge = "กำลังฟังเสียงของคุณ…";
    statusBadgeClass = "badge-listening";
  } else if (currentJobState === "transcribing") {
    statusBadge = "Whisper กำลังถอดเสียง…";
    statusBadgeClass = "badge-processing";
  } else if (currentJobState === "planning") {
    statusBadge = "AI กำลังวางแผนคำสั่ง…";
    statusBadgeClass = "badge-processing";
  } else if (currentJobState === "awaiting_confirm") {
    statusBadge = "รอการยืนยันความปลอดภัย";
    statusBadgeClass = "badge-warning";
  } else if (busy) {
    statusBadge = "PC กำลังประมวลผลคำสั่ง…";
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
                ? "ปล่อยนิ้วเพื่อส่งคำสั่งเสียง"
                : "แตะเพื่อส่งคำสั่งเสียง"
              : mic.mode === "hold"
              ? "กดค้างไว้เพื่อพูดคำสั่งเสียง"
              : "แตะเพื่อเริ่มพูดคำสั่งเสียง"
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
                ? "ปล่อยเพื่อส่ง"
                : "แตะเพื่อส่ง"
              : mic.mode === "hold"
              ? "กดค้างเพื่อพูด"
              : "แตะเพื่อเริ่มพูด"}
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
            title="กดค้างขณะพูด แล้วปล่อยเพื่อส่ง"
          >
            โหมดกดค้าง (Hold)
          </button>
          <button
            type="button"
            className={`mode-pill ${mic.mode === "tap" ? "active" : ""}`}
            onClick={() => mic.setMode("tap")}
            title="แตะหนึ่งครั้งเพื่อเริ่มพูด และแตะอีกครั้งเพื่อส่ง"
          >
            โหมดแตะสลับ (Tap)
          </button>
        </div>
        <p className="shortcut-hint">กด Spacebar ค้างเพื่อพูดได้เช่นกัน</p>
      </div>

      {/* Error & Warning Diagnostic Hints */}
      {mic.state === "denied" && (
        <div className="hint-card hint-error">
          <strong>ไม่ได้รับสิทธิ์เข้าถึงไมโครโฟน</strong>
          <p>กรุณากดไอคอนรูปกุญแจ/การตั้งค่าที่แถบ URL ของเบราว์เซอร์ แล้วเลือก อนุญาต (Allow) การใช้งาน Microphone หรือพิมพ์คำสั่งด้านล่างแทน</p>
        </div>
      )}
      {mic.state === "insecure" && (
        <div className="hint-card hint-warn">
          <strong>เบราว์เซอร์จำกัดสิทธิ์ความปลอดภัย (Insecure Context)</strong>
          <p>ไมโครโฟนบนอุปกรณ์มือถือใช้งานได้เฉพาะผ่าน HTTPS เท่านั้น กรุณาเข้าใช้งานผ่านที่อยู่ https:// ของ PC1 หรือใช้การพิมพ์คำสั่ง</p>
        </div>
      )}
      {mic.state === "unsupported" && (
        <div className="hint-card hint-info">
          <strong>เบราว์เซอร์นี้ไม่รองรับ MediaRecorder API</strong>
          <p>คุณสามารถพิมพ์คำสั่งในช่องด้านล่างเพื่อสั่งการเครื่องคอมพิวเตอร์แทนได้ทันที</p>
        </div>
      )}
    </div>
  );
}
