import { SparklesIcon } from "./Icons";

interface TranscriptionPanelProps {
  /** The most recent command text or transcription result */
  jobText: string | null;
  /** Whether the microphone is actively recording */
  isListening: boolean;
  /** Whether the server is currently processing or executing */
  isProcessing?: boolean;
}

/**
 * Live transcription panel showing recognized speech or current command context.
 */
export function TranscriptionPanel({
  jobText,
  isListening,
  isProcessing = false,
}: TranscriptionPanelProps) {
  return (
    <div
      className={`transcription-panel ${isListening ? "listening" : ""} ${
        isProcessing ? "processing" : ""
      }`}
      aria-live="polite"
      aria-atomic="true"
    >
      <div className="transcription-inner">
        {isListening ? (
          <div className="transcription-state-row">
            <span className="live-pill">
              <span className="live-dot" />
              Listening
            </span>
            <p className="transcription-hint">Speak in English clearly…</p>
          </div>
        ) : isProcessing ? (
          <div className="transcription-state-row">
            <span className="processing-pill">
              <SparklesIcon size={14} className="spin-slow" />
              Processing command
            </span>
            {jobText && <p className="transcription-text">“{jobText}”</p>}
          </div>
        ) : jobText ? (
          <div className="transcription-result-row">
            <span className="last-cmd-label">Last command</span>
            <p className="transcription-text">“{jobText}”</p>
          </div>
        ) : (
          <div className="transcription-empty-row">
            <p className="transcription-placeholder">
              Tap the mic and speak — e.g. <em>“open YouTube”</em> or <em>“mute volume”</em>
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
