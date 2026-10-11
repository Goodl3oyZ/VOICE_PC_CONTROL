import { useEffect, useState } from "react";
import type { Api, Capabilities } from "../api";
import { SparklesIcon, XIcon } from "./Icons";

interface CommandGuideProps {
  isOpen: boolean;
  api: Api;
  onClose: () => void;
  onRun: (command: string) => void;
}

/**
 * "What can I say?" — loaded from the server (GET /capabilities), so it always matches what PC1 accepts.
 * Every example is covered by a server test that parses it and checks the safety policy allows it.
 * Tapping an example runs it.
 */
export function CommandGuide({ isOpen, api, onClose, onRun }: CommandGuideProps) {
  const [caps, setCaps] = useState<Capabilities | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isOpen || caps) return;
    api
      .capabilities()
      .then(setCaps)
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [isOpen, caps, api]);

  if (!isOpen) return null;

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="guide-title">
      <div className="modal-dialog command-guide" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <SparklesIcon size={20} />
            <h3 id="guide-title">What can I say?</h3>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close">
            <XIcon size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">
            Speak or type <strong>in English</strong>. Tap any example to run it now. You can also say “help”.
          </p>
          {error && <div className="setup-error-msg">Could not load the command list: {error}</div>}
          {!caps && !error && <p className="modal-desc">Loading…</p>}

          {caps?.groups.map((g) => (
            <section key={g.id} className="guide-group">
              <div className="guide-group-head">
                <h4>{g.title}</h4>
                <span className="guide-hint">{g.hint}</span>
              </div>
              <div className="guide-examples">
                {g.examples.map((ex) => (
                  <button
                    key={ex}
                    type="button"
                    className="chip-btn"
                    onClick={() => {
                      onRun(ex);
                      onClose();
                    }}
                  >
                    {ex}
                  </button>
                ))}
              </div>
            </section>
          ))}

          {caps && (
            <>
              <section className="guide-group">
                <h4>Allowed apps and websites</h4>
                <p className="guide-list">Apps: {caps.apps.join(", ")}</p>
                <p className="guide-list">Websites: {caps.sites.join(", ")}</p>
              </section>
              <section className="guide-group guide-refused">
                <h4>Not allowed (refused, nothing runs)</h4>
                <ul>
                  {caps.refused.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              </section>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
