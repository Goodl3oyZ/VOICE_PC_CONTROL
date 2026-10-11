import { useState, type FormEvent } from "react";
import { SendIcon, SparklesIcon, AlertCircleIcon } from "./Icons";

interface CommandInputProps {
  onSubmitText: (text: string) => void;
  busy: boolean;
  error: string | null;
  onClearError: () => void;
  onOpenGuide: () => void;
}

const QUICK_SUGGESTIONS = [
  "Open Chrome",
  "Play lofi on YouTube",
  "Next song",
  "Mute",
  "Volume up 20%",
  "Status",
];

export function CommandInput({ onSubmitText, busy, error, onClearError, onOpenGuide }: CommandInputProps) {
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
      <div className="suggestion-chips-bar" aria-label="Example commands">
        <span className="chips-label">
          <SparklesIcon size={14} /> Try:
        </span>
        <div className="chips-scroll">
          <button type="button" className="chip-btn chip-guide" onClick={onOpenGuide}>
            All commands…
          </button>
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
            placeholder="Or type in English, e.g. open YouTube, next song…"
            maxLength={1000}
            aria-label="Type a command for the PC"
          />
          <button
            type="submit"
            className="command-send-button"
            disabled={!text.trim()}
            title="Send command"
            aria-label="Send command"
          >
            <SendIcon size={18} />
            <span className="send-text">Send</span>
          </button>
        </div>
      </form>

      {/* Status Indicators */}
      {busy && (
        <div className="input-hint-row queue-hint">
          <span className="pulse-indicator cyan" />
          <span>A command is still running — new commands are queued automatically</span>
        </div>
      )}

      {error && (
        <div className="input-error-banner" role="alert">
          <AlertCircleIcon size={16} />
          <span className="error-text">{error}</span>
          <button type="button" className="error-dismiss" onClick={onClearError} aria-label="Dismiss error">
            ✕
          </button>
        </div>
      )}
    </div>
  );
}
