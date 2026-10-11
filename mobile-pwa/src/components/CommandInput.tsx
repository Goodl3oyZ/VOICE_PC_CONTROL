import { useState, type FormEvent } from "react";
import { SendIcon, SparklesIcon, AlertCircleIcon } from "./Icons";

interface CommandInputProps {
  onSubmitText: (text: string) => void;
  busy: boolean;
  error: string | null;
  onClearError: () => void;
}

const QUICK_SUGGESTIONS = [
  "เปิด Google Chrome",
  "เปิด Spotify",
  "เปิด Notepad",
  "ปิดเสียง",
  "เพิ่มเสียง 20%",
  "ตรวจสถานะเครื่อง",
];

export function CommandInput({ onSubmitText, busy, error, onClearError }: CommandInputProps) {
  const [text, setText] = useState("");

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const clean = text.trim();
    if (!clean) return;
    onSubmitText(clean);
    setText("");
    if (error) onClearError();
  };

  const handleChipClick = (suggestion: string) => {
    onSubmitText(suggestion);
    if (error) onClearError();
  };

  return (
    <div className="command-input-container">
      {/* Suggestion Chips */}
      <div className="suggestion-chips-bar" aria-label="คำสั่งตัวอย่าง">
        <span className="chips-label">
          <SparklesIcon size={14} /> แนะนำ:
        </span>
        <div className="chips-scroll">
          {QUICK_SUGGESTIONS.map((sugg) => (
            <button
              key={sugg}
              type="button"
              className="chip-btn"
              onClick={() => handleChipClick(sugg)}
            >
              {sugg}
            </button>
          ))}
        </div>
      </div>

      {/* Input Form */}
      <form className="command-form" onSubmit={handleSubmit}>
        <div className="input-field-wrapper">
          <input
            type="text"
            className="command-text-input"
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              if (error) onClearError();
            }}
            placeholder="หรือพิมพ์คำสั่ง เช่น เปิด YouTube, ปิดเครื่อง…"
            maxLength={1000}
            aria-label="พิมพ์คำสั่งเพื่อส่งไปยัง PC"
          />
          <button
            type="submit"
            className="command-send-button"
            disabled={!text.trim()}
            title="ส่งคำสั่ง"
            aria-label="ส่งคำสั่ง"
          >
            <SendIcon size={18} />
            <span className="send-text">ส่ง</span>
          </button>
        </div>
      </form>

      {/* Status Indicators */}
      {busy && (
        <div className="input-hint-row queue-hint">
          <span className="pulse-indicator cyan" />
          <span>มีงานกำลังทำงานอยู่ — คำสั่งใหม่จะถูกจัดเข้าคิวอัตโนมัติ</span>
        </div>
      )}

      {error && (
        <div className="input-error-banner" role="alert">
          <AlertCircleIcon size={16} />
          <span className="error-text">{error}</span>
          <button type="button" className="error-dismiss" onClick={onClearError} aria-label="ปิดข้อความผิดพลาด">
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
