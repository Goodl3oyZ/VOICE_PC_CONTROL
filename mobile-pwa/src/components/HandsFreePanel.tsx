import type { HandsFreeState } from "../useHandsFree";

interface HandsFreePanelProps {
  state: HandsFreeState;
  error: string | null;
  on: boolean;
  onToggle: () => void;
  speakOn: boolean;
  onToggleSpeak: () => void;
}

const STATUS: Record<HandsFreeState, string> = {
  off: "Off — say commands with the mic button",
  starting: "Starting the microphone…",
  waiting: "Listening for “computer, …”",
  hearing: "Hearing speech…",
  sending: "Checking what you said…",
  armed: "Yes? Say your command",
  error: "Hands-free stopped",
};

/** Phase 4: wake-word listening + spoken replies. */
export function HandsFreePanel({ state, error, on, onToggle, speakOn, onToggleSpeak }: HandsFreePanelProps) {
  return (
    <div className={`hands-free-panel ${on ? "is-on" : ""}`}>
      <label className="hf-row">
        <input type="checkbox" role="switch" checked={on} onChange={onToggle} />
        <span className="hf-label">
          <strong>Hands-free</strong>
          <span className={`hf-status hf-${state}`} aria-live="polite">
            {STATUS[state]}
          </span>
        </span>
      </label>
      <label className="hf-row">
        <input type="checkbox" role="switch" checked={speakOn} onChange={onToggleSpeak} />
        <span className="hf-label">
          <strong>Speak results</strong>
          <span className="hf-status">The phone reads results aloud</span>
        </span>
      </label>
      {on && (
        <p className="hf-hint">
          Start with <strong>“computer”</strong>, e.g. “computer, open Chrome”. Say <strong>“stop”</strong> to stop a
          running command. Only what follows “computer” is used; other speech is ignored and not stored. Keep this
          screen open.
        </p>
      )}
      {error && <p className="hf-error">{error}</p>}
    </div>
  );
}
