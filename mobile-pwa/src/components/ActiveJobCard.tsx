import { useEffect, useRef, useState, type FormEvent } from "react";
import type { Api, Job } from "../api";
import {
  STATE_TH,
  STATE_DESC_TH,
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
  ShieldAlertIcon,
  SparklesIcon,
  XIcon,
} from "./Icons";

interface ActiveJobCardProps {
  job: Job;
  api: Api;
  onError: (e: unknown) => void;
  onUpdate: (j: Job) => void;
}

export function ActiveJobCard({ job, api, onError, onUpdate }: ActiveJobCardProps) {
  const [answer, setAnswer] = useState("");
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
          <span className="state-title">{STATE_TH[job.state]}</span>
        </div>

        <div className="job-meta-pills">
          <span className="job-source-pill">{job.source === "audio" ? "เสียงพูด" : "ข้อความ"}</span>
          {job.timings_ms.total !== undefined && (
            <span className="job-timing-pill">
              <ClockIcon size={13} />
              {formatDuration(job.timings_ms.total)}
            </span>
          )}
        </div>
      </div>

      {/* State explanation note */}
      <p className="job-state-desc">{STATE_DESC_TH[job.state]}</p>

      {/* Spoken / Prompt text */}
      {job.text && (
        <div className="job-prompt-box">
          <span className="quote-mark">“</span>
          <span className="prompt-text">{job.text}</span>
          <span className="quote-mark">”</span>
          {job.stt_confidence !== null && job.stt_confidence !== undefined && (
            <span className="stt-confidence" title="ความแม่นยำของการถอดเสียง">
              ถอดเสียงแม่นยำ {(job.stt_confidence * 100).toFixed(0)}%
            </span>
          )}
        </div>
      )}

      {/* Clarification prompt */}
      {job.state === "clarifying" && job.question && (
        <div className="clarification-panel">
          <div className="question-header">
            <SparklesIcon size={16} />
            <span className="question-title">ระบบต้องการข้อมูลเพิ่มเติม:</span>
          </div>
          <p className="clarification-question">{job.question}</p>
          <form className="clarification-form" onSubmit={handleClarifySubmit}>
            <input
              type="text"
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="พิมพ์คำตอบของคุณที่นี่…"
              autoFocus
              maxLength={1000}
              className="clarification-input"
            />
            <button type="submit" className="clarification-submit" disabled={!answer.trim()}>
              ตอบกลับ
            </button>
          </form>
        </div>
      )}

      {/* Safety Confirmation dialogue (§20.5) */}
      {job.state === "awaiting_confirm" && job.pending && (
        <div className="confirm-safety-panel">
          <div className="confirm-banner">
            <ShieldAlertIcon size={20} />
            <div>
              <div className="confirm-risk-title">{riskLabel(job.pending.risk)}</div>
              <div className="confirm-timer">
                {remainingSecs > 0 ? (
                  <>กรุณายืนยันภายใน <strong>{remainingSecs}</strong> วินาที</>
                ) : (
                  <span className="expired">หมดเวลายืนยันแล้ว</span>
                )}
              </div>
            </div>
          </div>

          <div className="confirm-call-breakdown">
            <div className="breakdown-label">พารามิเตอร์คำสั่งที่จะส่งไปยัง PC:</div>
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
              <span>อนุมัติคำสั่ง</span>
            </button>
            <button
              type="button"
              className="btn-reject"
              onClick={() => act(api.confirm(job.id, false, job.pending!.args_hash))}
            >
              <XIcon size={18} />
              <span>ยกเลิก</span>
            </button>
          </div>
        </div>
      )}

      {/* Execution steps breakdown */}
      {job.steps && job.steps.length > 0 && (
        <div className="job-steps-wrapper">
          <div className="steps-header">
            <CpuIcon size={14} />
            <span>ขั้นตอนการดำเนินการบน PC ({job.steps.length} ขั้นตอน):</span>
          </div>
          <div className="steps-list">
            {job.steps.map((st, idx) => (
              <div key={idx} className={`step-item ${st.result?.ok ? "step-ok" : "step-fail"}`}>
                <span className="step-num">{idx + 1}</span>
                <span className="step-tool">{st.tool}</span>
                {st.result && (
                  <span className={`step-badge ${st.result.ok ? "badge-success" : "badge-error"}`}>
                    {st.result.ok ? "สำเร็จ" : "ล้มเหลว"}
                    {st.result.verified && " (ตรวจแล้ว)"}
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
          <div className="summary-title">ผลลัพธ์การทำงาน:</div>
          <div className="summary-body">{job.summary}</div>
        </div>
      )}

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
              <span className="label">ถอดเสียง:</span>
              <span className="val">{formatDuration(job.timings_ms.stt)}</span>
            </div>
          )}
          {job.timings_ms.planning !== undefined && (
            <div className="timing-chip">
              <span className="label">วางแผน:</span>
              <span className="val">{formatDuration(job.timings_ms.planning)}</span>
            </div>
          )}
          {job.timings_ms.exec !== undefined && (
            <div className="timing-chip">
              <span className="label">สั่งการ PC:</span>
              <span className="val">{formatDuration(job.timings_ms.exec)}</span>
            </div>
          )}
        </div>
      )}
    </article>
  );
}
