import type { Job } from "../api";
import { STATE_LABEL, TERMINAL } from "../labels";
import { AlertCircleIcon, CheckCircleIcon, ChevronDownIcon, ClockIcon } from "./Icons";

interface Props {
  job: Job;
  open: boolean;
  onToggle: () => void;
}

/** One line under the orb: what the last command did. Tap for the full card (steps, timings, retry). */
export function LastResult({ job, open, onToggle }: Props) {
  const done = job.state === "done";
  const working = !TERMINAL.has(job.state);
  const tone = done ? "ok" : working ? "busy" : "bad";
  const text = working
    ? `${job.text} · ${STATE_LABEL[job.state]}`
    : done
      ? job.summary || job.text
      : job.error || STATE_LABEL[job.state];
  const Icon = done ? CheckCircleIcon : working ? ClockIcon : AlertCircleIcon;
  return (
    <button
      type="button"
      className={`last-result tone-${tone} ${open ? "is-open" : ""}`}
      onClick={onToggle}
      aria-expanded={open}
      title={open ? "Hide details" : "Show details"}
    >
      <Icon size={16} className="last-result-icon" />
      <span className="last-result-text">{text}</span>
      <ChevronDownIcon size={16} className="last-result-chevron" />
    </button>
  );
}
