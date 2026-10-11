/**
 * Always-visible notice: the speech model on this server is reliable in English only, so commands in any
 * other language are rejected by the server ("Only English is supported…") instead of being guessed.
 */
export function EnglishOnlyNotice({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`english-only-notice${compact ? " compact" : ""}`} role="note" aria-label="Language notice">
      <span className="eon-flag" aria-hidden="true">EN</span>
      <div className="eon-text">
        <strong>English only.</strong>{" "}
        <span>
          Speak or type your commands in English, e.g. “open Chrome”, “next song”, “search weather in Bangkok”.
          Commands in other languages (including Thai) are rejected and nothing is run.
        </span>
      </div>
    </div>
  );
}
