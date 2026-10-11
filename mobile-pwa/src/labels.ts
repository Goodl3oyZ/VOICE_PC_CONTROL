import type { Job, JobState } from "./api";

export const STATE_LABEL: Record<JobState, string> = {
  created: "Received",
  transcribing: "Transcribing…",
  planning: "Planning…",
  clarifying: "Waiting for your answer",
  routing: "Checking permissions…",
  awaiting_confirm: "Waiting for your confirmation",
  dispatching: "Sending to PC2…",
  running: "PC2 is working…",
  verifying: "Verifying…",
  done: "Done",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const STATE_EN: Record<JobState, string> = {
  created: "Command Received",
  transcribing: "Transcribing Audio…",
  planning: "Planning Actions…",
  clarifying: "Clarification Needed",
  routing: "Checking Permissions…",
  awaiting_confirm: "Confirmation Required",
  dispatching: "Dispatching to PC…",
  running: "Executing on PC…",
  verifying: "Verifying Result…",
  done: "Completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export const STATE_DESC: Record<JobState, string> = {
  created: "The command was received and is queued",
  transcribing: "Converting your speech to text (Whisper)",
  planning: "The AI is working out what to do",
  clarifying: "Please answer the question below (in English)",
  routing: "Checking permissions and risk level",
  awaiting_confirm: "This action has an effect outside the PC — check the details before approving",
  dispatching: "Sending the signed command to the PC",
  running: "The PC is carrying out the command",
  verifying: "Checking that it really worked",
  done: "Completed successfully",
  failed: "Something went wrong",
  cancelled: "Cancelled by you or timed out",
};

export const TERMINAL: ReadonlySet<JobState> = new Set(["done", "failed", "cancelled"]);

export function isActive(job: Job): boolean {
  return !TERMINAL.has(job.state);
}

const RISK_LABELS = [
  "Level 0: read-only (safe)",
  "Level 1: open apps",
  "Level 2: limited changes",
  "Level 3: external effect / hard to undo",
  "Level 4: forbidden by default",
];

export const riskLabel = (risk: number) => RISK_LABELS[risk] ?? `Risk level ${risk}`;

/** Confirmation card text is built from the real tool + arguments, never from LLM prose (§20.5). */
export function describeCall(tool: string, args: Record<string, unknown>): string[] {
  return [`Tool: ${tool}`, ...Object.entries(args).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)];
}

/** Merge an updated job into the newest-first list (max 50). */
export function upsertJob(list: Job[], job: Job): Job[] {
  const i = list.findIndex((j) => j.id === job.id);
  if (i >= 0) {
    const copy = list.slice();
    copy[i] = job;
    return copy;
  }
  return [job, ...list].slice(0, 50);
}

export function secondsLeft(expiresAt: number, nowMs = Date.now()): number {
  return Math.max(0, Math.round(expiresAt - nowMs / 1000));
}

export function formatDuration(ms?: number): string {
  if (ms === undefined || ms === null) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

export function formatTime(timestampSeconds: number): string {
  try {
    return new Date(timestampSeconds * 1000).toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}
