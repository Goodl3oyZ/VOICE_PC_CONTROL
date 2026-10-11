import { useState } from "react";
import { XIcon } from "./Icons";

/**
 * Notice: speech model on this server is reliable in English only.
 * Dismissible by user to avoid cluttering screen.
 */
export function EnglishOnlyNotice({ compact = false }: { compact?: boolean }) {
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem("vpc.hide_en_notice") === "1";
    } catch {
      return false;
    }
  });

  if (dismissed) return null;

  const handleDismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem("vpc.hide_en_notice", "1");
    } catch {
      /* ignore */
    }
  };

  return (
    <div className={`english-only-notice${compact ? " compact" : ""}`} role="note" aria-label="Language notice">
      <span className="eon-flag" aria-hidden="true">EN</span>
      <div className="eon-text">
        <strong>English only.</strong>{" "}
        <span>
          Speak or type commands in English (e.g. “open Chrome”, “next song”).
        </span>
      </div>
      <button
        type="button"
        className="eon-dismiss"
        onClick={handleDismiss}
        aria-label="Dismiss language notice"
      >
        <XIcon size={14} />
      </button>
    </div>
  );
}

