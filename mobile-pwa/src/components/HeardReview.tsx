import { useEffect, useRef, useState, type FormEvent } from "react";
import { MicIcon, XIcon } from "./Icons";

export interface Heard {
  text: string;
  confidence: number;
}

interface Props {
  heard: Heard | "listening" | { error: string };
  onSend: (text: string) => void;
  onRetry: () => void;
  onCancel: () => void;
}

/** What PC1 heard, shown before anything runs: send it, fix the words, or say it again. */
export function HeardReview({ heard, onSend, onRetry, onCancel }: Props) {
  const [text, setText] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const got = typeof heard === "object" && "text" in heard ? heard : null;

  useEffect(() => {
    if (got) setText(got.text);
  }, [got]);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (text.trim()) onSend(text.trim());
  };

  if (heard === "listening") {
    return (
      <div className="heard-review is-busy" aria-live="polite">
        <span className="heard-label">Working out what you said…</span>
      </div>
    );
  }
  if (!got) {
    return (
      <div className="heard-review is-error" role="alert">
        <span className="heard-label">{(heard as { error: string }).error}</span>
        <div className="heard-actions">
          <button type="button" className="heard-btn heard-retry" onClick={onRetry}>
            <MicIcon size={16} /> Try again
          </button>
          <button type="button" className="heard-btn heard-cancel" onClick={onCancel}>
            Close
          </button>
        </div>
      </div>
    );
  }
  const unsure = got.confidence < 0.55;
  return (
    <form className={`heard-review ${unsure ? "is-unsure" : ""}`} onSubmit={submit} aria-live="polite">
      <div className="heard-head">
        <span className="heard-label">{unsure ? "Not sure I heard right. Check it:" : "I heard:"}</span>
        <button type="button" className="heard-x" onClick={onCancel} aria-label="Discard">
          <XIcon size={16} />
        </button>
      </div>
      <textarea
        ref={input}
        className="heard-text"
        value={text}
        rows={Math.min(4, Math.max(1, Math.ceil(text.length / 34)))}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) submit(e);
        }}
        aria-label="What you said (you can edit it)"
      />
      <p className="heard-hint">Tap the text to fix a word. Nothing runs until you press Send.</p>
      <div className="heard-actions">
        <button type="submit" className="heard-btn heard-send" disabled={!text.trim()}>
          Send
        </button>
        <button type="button" className="heard-btn heard-retry" onClick={onRetry}>
          <MicIcon size={16} /> Say again
        </button>
      </div>
    </form>
  );
}
