import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Api, Job } from "../api";
import { CodeChangesPanel } from "./CodeChangesPanel";
import { VoiceAnswerButton } from "./VoiceAnswerButton";
import {
  STATE_LABEL,
  STATE_DESC,
  describeCall,
  formatDuration,
  riskLabel,
  secondsLeft,
} from "../labels";
import {
  AlertTriangleIcon,
  CheckCircleIcon,
  ClockIcon,
  CpuIcon,
  MicIcon,
  ShieldAlertIcon,
  SparklesIcon,
  XIcon,
} from "./Icons";

interface ActiveJobCardProps {
  job: Job;
  api: Api;
  onError: (e: unknown) => void;
  onUpdate: (j: Job) => void;
  onNewJob: (p: Promise<Job>) => void;
}

export function ActiveJobCard({ job, api, onError, onUpdate, onNewJob }: ActiveJobCardProps) {
  const [answer, setAnswer] = useState("");
  const [typing, setTyping] = useState(false);
  const sent = useRef(false);

  useEffect(() => {
    sent.current = false;
  }, [job.id, job.state]);

  const act = (p: Promise<Job>) => {
    if (sent.current) return;
    sent.current = true;
    p.then(onUpdate).catch((e) => {
      sent.current = false;
      onError(e);
    });
  };

  const handleClarifySubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!answer.trim()) return;
    act(api.reply(job.id, answer.trim()));
    setAnswer("");
  };

  const remainingSecs = job.pending ? secondsLeft(job.pending.expires_at) : 0;
  const isTerminal = job.state === "done" || job.state === "failed" || job.state === "cancelled";

  return (
    <article className={`active-job-card card-state-${job.state}`} aria-live="polite">
      {/* Header status bar */}
      <div className="job-card-header">
        <div className="job-state-badge">
          {job.state === "done" ? (
            <CheckCircleIcon size={16} />
          ) : job.state === "failed" || job.state === "cancelled" ? (
            <AlertTriangleIcon size={16} />
          ) : job.state === "awaiting_confirm" ? (
            <ShieldAlertIcon size={16} />
          ) : (
            <SparklesIcon size={16} className="spin-slow" />
          )}
          <span className="state-title">{STATE_LABEL[job.state]}</span>
        </div>

        <div className="job-meta-pills">
          <span className="job-source-pill">{job.source === "audio" ? "Voice" : "Text"}</span>
          {job.timings_ms.total !== undefined && (
            <span className="job-timing-pill">
              <ClockIcon size={13} />
              {formatDuration(job.timings_ms.total)}
            </span>
          )}
        </div>
      </div>

      {/* State explanation note */}
      <p className="job-state-desc">{STATE_DESC[job.state]}</p>

      {/* Spoken / Prompt text */}
      {job.text && (
        <div className="job-prompt-box">
          <span className="quote-mark">“</span>
          <span className="prompt-text">{job.text}</span>
          <span className="quote-mark">”</span>
          {job.stt_confidence !== null && job.stt_confidence !== undefined && (
            <span className="stt-confidence" title="Speech recognition confidence">
              Recognition confidence {(job.stt_confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      )}

      {/* Clarification prompt */}
      {job.state === "clarifying" && job.question && (
        <div className="clarification-panel">
          {job.clarify_kind === "stt_confirm" ? (
            <>
              <div className="question-header">
                <MicIcon size={16} />
                <span className="question-title">Not sure I heard you right</span>
              </div>
              <p className="clarification-heard">“{job.text}”</p>
              <div className="clarify-actions">
                <button type="button" className="btn-approve" onClick={() => act(api.reply(job.id, "yes"))}>
                  <CheckCircleIcon size={18} />
                  <span>Yes, do it</span>
                </button>
                <VoiceAnswerButton api={api} label="Say it again" className="clarify-voice"
                  onText={(t) => act(api.reply(job.id, t))} onError={onError} />
              </div>
            </>
          ) : (
            <>
              <div className="question-header">
                <SparklesIcon size={16} />
                <span className="question-title">More information needed:</span>
              </div>
              <p className="clarification-question">{job.question}</p>
              <VoiceAnswerButton api={api} label="Answer by voice" className="clarify-voice"
                onText={(t) => act(api.reply(job.id, t))} onError={onError} />
            </>
          )}
          {typing || job.clarify_kind !== "stt_confirm" ? (
            <form className="clarification-form" onSubmit={handleClarifySubmit}>
              <input
                type="text"
                value={answer}
                onChange={(e) => setAnswer(e.target.value)}
                placeholder={job.clarify_kind === "stt_confirm" ? "Type the command…" : "Or type your answer…"}
                maxLength={1000}
                className="clarification-input"
              />
              <button type="submit" className="clarification-submit" disabled={!answer.trim()}>
                Send
              </button>
            </form>
          ) : (
            <button type="button" className="clarify-type-link" onClick={() => setTyping(true)}>
              Type it instead
            </button>
          )}
        </div>
      )}

      {/* Safety Confirmation dialogue (§20.5) */}
      {job.state === "awaiting_confirm" && job.pending && (
        <div className="confirm-safety-panel">
          <div className="confirm-banner">
            <ShieldAlertIcon size={20} />
            <div>
              <div className="confirm-risk-title">{riskLabel(job.pending.risk)}</div>
              {job.pending.reason.startsWith("risky code: ") && (
                <div className="confirm-reason">
                  The AI's edit {job.pending.reason.slice(12)}. Approve only if you asked for that.
                </div>
              )}
              <div className="confirm-timer">
                {remainingSecs > 0 ? (
                  <>Please confirm within <strong>{remainingSecs}</strong> seconds</>
                ) : (
                  <span className="expired">Confirmation expired</span>
                )}
              </div>
            </div>
          </div>

          <div className="confirm-call-breakdown">
            <div className="breakdown-label">Parameters that will be sent to the PC:</div>
            <ul className="breakdown-list">
              {describeCall(job.pending.tool, job.pending.arguments).map((line) => (
                <li key={line}>
                  <code>{line}</code>
                </li>
              ))}
            </ul>
          </div>

          <div className="confirm-actions-row">
            <button
              type="button"
              className="btn-approve"
              disabled={remainingSecs <= 0}
              onClick={() => act(api.confirm(job.id, true, job.pending!.args_hash))}
            >
              <CheckCircleIcon size={18} />
              <span>Approve</span>
            </button>
            <button
              type="button"
              className="btn-reject"
              onClick={() => act(api.confirm(job.id, false, job.pending!.args_hash))}
            >
              <XIcon size={18} />
              <span>Cancel</span>
            </button>
          </div>
        </div>
      )}

      {/* Execution steps breakdown */}
      {job.steps && job.steps.length > 0 && (
        <div className="job-steps-wrapper">
          <div className="steps-header">
            <CpuIcon size={14} />
            <span>Steps on the PC ({job.steps.length}):</span>
          </div>
          <div className="steps-list">
            {job.steps.map((st, idx) => (
              <div key={idx} className={`step-item ${st.result?.ok ? "step-ok" : "step-fail"}`}>
                <span className="step-num">{idx + 1}</span>
                <span className="step-tool">{st.tool}</span>
                {st.result && (
                  <span className={`step-badge ${st.result.ok ? "badge-success" : "badge-error"}`}>
                    {st.result.ok ? "OK" : "Failed"}
                    {st.result.verified && " (verified)"}
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Summary report */}
      {job.summary && job.state !== "clarifying" && (
        <div className="job-summary-box">
          <div className="summary-title">Result:</div>
          <div className="summary-body">{job.summary}</div>
        </div>
      )}

      {/* Phase 3: diff + revert for coding jobs */}
      {isTerminal && <CodeChangesPanel job={job} api={api} onNewJob={onNewJob} />}

      {/* Error report */}
      {job.error && (
        <div className="job-error-box">
          <AlertTriangleIcon size={16} />
          <span>{job.error}</span>
        </div>
      )}

      {/* Detailed Timing Diagnostics */}
      {isTerminal && Object.keys(job.timings_ms).length > 1 && (
        <div className="job-timings-grid">
          {job.timings_ms.stt !== undefined && (
            <div className="timing-chip">
              <span className="label">Speech:</span>
              <span className="val">{formatDuration(job.timings_ms.stt)}</span>
            </div>
          )}
          {job.timings_ms.plan !== undefined && (
            <div className="timing-chip">
              <span className="label">Planning:</span>
              <span className="val">{formatDuration(job.timings_ms.plan)}</span>
            </div>
          )}
          {job.timings_ms.tool !== undefined && (
            <div className="timing-chip">
              <span className="label">PC action:</span>
              <span className="val">{formatDuration(job.timings_ms.tool)}</span>
            </div>
          )}
        </div>
      )}

      {/* Cancel: clears a job that waits for an answer/confirmation or is still running */}
      {!isTerminal && (
        <button type="button" className="btn-modal-logout job-cancel-btn" onClick={() => act(api.cancel(job.id))}>
          <XIcon size={14} />
          <span>Cancel this job</span>
        </button>
      )}
    </article>
  );
}
