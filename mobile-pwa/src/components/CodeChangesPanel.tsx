import type { Api, Job } from "../api";
import { codeContext, diffLineKind } from "../labels";
import { CpuIcon, XIcon } from "./Icons";

interface CodeChangesPanelProps {
  job: Job;
  api: Api;
  onNewJob: (p: Promise<Job>) => void;
}

/** Phase 3 (US-505): see what the AI changed and undo it from the phone. */
export function CodeChangesPanel({ job, api, onNewJob }: CodeChangesPanelProps) {
  const ctx = codeContext(job);
  if (!ctx) return null;

  const revert = () => {
    const ok = window.confirm(
      `Undo ALL AI changes in “${ctx.project}”?\n\nThe AI branch will be deleted and the project goes back to its base branch.`,
    );
    if (ok) onNewJob(api.sendText(`revert the changes in ${ctx.project}`));
  };

  return (
    <div className="code-changes-panel">
      <div className="steps-header">
        <CpuIcon size={14} />
        <span>
          Code changes in <strong>{ctx.project}</strong>
          {ctx.files.length > 0 && ` · ${ctx.files.length} file(s)`}
        </span>
      </div>

      {ctx.diff && (
        <pre className="diff-view" aria-label="Diff">
          {ctx.diff.split("\n").map((line, i) => (
            <span key={i} className={`diff-line diff-${diffLineKind(line)}`}>
              {line || " "}
              {"\n"}
            </span>
          ))}
        </pre>
      )}

      <div className="code-actions-row">
        {!ctx.diff && (
          <button
            type="button"
            className="btn-code"
            onClick={() => onNewJob(api.sendText(`show the diff for ${ctx.project}`))}
          >
            Show diff
          </button>
        )}
        <button
          type="button"
          className="btn-code"
          onClick={() => onNewJob(api.sendText(`run the tests in ${ctx.project}`))}
        >
          Run tests
        </button>
        {ctx.hasChanges && (
          <button type="button" className="btn-code btn-code-danger" onClick={revert}>
            <XIcon size={14} />
            <span>Revert</span>
          </button>
        )}
      </div>
    </div>
  );
}
