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

/** Phase 3: what the phone shows for a job that touched a code project (diff + revert). */
export interface CodeContext {
  project: string;
  diff: string | null;
  files: string[];
  hasChanges: boolean;
}

const CODE_TOOLS = new Set(["edit_file", "run_tests", "git_diff", "git_status", "read_file", "search_code", "list_files"]);

export function codeContext(job: Job): CodeContext | null {
  const steps = job.steps || [];
  const coding = steps.filter((s) => CODE_TOOLS.has(s.tool) && typeof s.arguments.project === "string");
  if (coding.length === 0) return null;
  const last = steps[steps.length - 1];
  if (last && last.tool === "revert_changes") return null;
  const project = coding[0].arguments.project as string;
  const diffStep = [...steps].reverse().find((s) => s.tool === "git_diff" && s.result.ok);
  const diffData = diffStep?.result.data ?? {};
  const files = Array.isArray(diffData.files) ? (diffData.files as string[]) : [];
  const edited = steps.some((s) => s.tool === "edit_file" && s.result.ok);
  const diff = typeof diffData.diff === "string" && diffData.diff ? (diffData.diff as string) : null;
  return { project, diff, files, hasChanges: edited || files.length > 0 };
}

export type DiffLineKind = "add" | "del" | "hunk" | "meta" | "ctx";

export function diffLineKind(line: string): DiffLineKind {
  if (line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("index ")) {
    return "meta";
  }
  if (line.startsWith("@@")) return "hunk";
  if (line.startsWith("+")) return "add";
  if (line.startsWith("-")) return "del";
  return "ctx";
}

/** Activity timeline: what happened, in words (never a tool name). */
export function jobHeadline(job: Job): string {
  if (job.state === "done") return job.summary || job.text || "Done";
  if (job.state === "cancelled") return job.error ? `Cancelled: ${job.error}` : "Cancelled";
  if (job.state === "failed") return job.error || job.summary || "That didn't work";
  if (job.state === "clarifying") return job.question || STATE_LABEL.clarifying;
  return STATE_LABEL[job.state];
}

export type JobKind = "media" | "skip" | "volume" | "search" | "app" | "screen" | "power" | "code" | "status" | "chat";

const KIND_BY_TOOL: Record<string, JobKind> = {
  youtube_play: "media", youtube_skip_ad: "skip", obs_control: "screen", obs_start_stream: "screen",
  web_search: "search", search_web: "search", open_result: "search",
  look_at_screen: "screen", describe_screen: "screen", wake_pc: "power", stop_all: "power", get_status: "status",
};

/** Picks the timeline icon from the last tool the job used. */
export function jobKind(job: Job): JobKind {
  const step = job.steps[job.steps.length - 1] ?? (job.pending ? { tool: job.pending.tool, arguments: job.pending.arguments } : null);
  if (!step) return "chat";
  const { tool, arguments: args } = step;
  if (tool === "media_control") {
    const action = String(args.action ?? "");
    if (action === "next" || action === "previous") return "skip";
    if (action.startsWith("volume") || action === "mute") return "volume";
    return "media";
  }
  if (KIND_BY_TOOL[tool]) return KIND_BY_TOOL[tool];
  if (CODE_TOOLS.has(tool) || /project/.test(tool) || tool === "revert_changes") return "code";
  return "app";
}

/** "Today", "Yesterday", or a short date, for the timeline's day headers. */
export function dayLabel(timestampSeconds: number, now = new Date()): string {
  const d = new Date(timestampSeconds * 1000);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(now) - start(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" });
}

export function formatClock(timestampSeconds: number): string {
  try {
    return new Date(timestampSeconds * 1000).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  } catch {
    return "";
  }
}
