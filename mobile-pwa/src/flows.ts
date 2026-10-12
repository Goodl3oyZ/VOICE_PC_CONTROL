// Wizard logic for app flows (pure functions, unit-tested in flows.test.ts).
import type { FlowDef, FlowOption, FlowStage, Job } from "./api";

export type Answers = Record<string, string>;

/** Stages that apply given the answers so far (e.g. "What should I look for?" only after "Play"/"Search"). */
export function activeStages(flow: FlowDef, answers: Answers): FlowStage[] {
  return flow.stages.filter((s) => !s.when || s.when.values.includes(answers[s.when.stage] ?? ""));
}

/** Answers remembered from last time (e.g. the music app) are filled in up front; the wizard shows them
 * as "Using YouTube · change" instead of asking again. */
export function startAnswers(flow: FlowDef): Answers {
  const a: Answers = {};
  for (const s of flow.stages) if (s.default) a[s.id] = s.default;
  return a;
}

/** The first stage still waiting for an answer, or null when the flow is ready to run. */
export function nextStage(flow: FlowDef, answers: Answers): FlowStage | null {
  return activeStages(flow, answers).find((s) => !answers[s.id]) ?? null;
}

/** "Step 2 of 3": counts only the stages that apply. */
export function stepInfo(flow: FlowDef, answers: Answers): { step: number; total: number } {
  // A conditional stage counts until the answer it depends on rules it out ("Step 1 of 2", not "of 1").
  const stages = flow.stages.filter((s) => !s.when || !answers[s.when.stage] || s.when.values.includes(answers[s.when.stage]));
  const answered = stages.filter((s) => answers[s.id]).length;
  return { step: Math.min(answered + 1, stages.length), total: stages.length };
}

/** Clearing an answer also clears every later answer that depended on it. */
export function clearFrom(flow: FlowDef, answers: Answers, stageId: string): Answers {
  const i = flow.stages.findIndex((s) => s.id === stageId);
  const out: Answers = {};
  flow.stages.forEach((s, j) => {
    if (j < i && answers[s.id]) out[s.id] = answers[s.id];
  });
  return out;
}

const ORDINALS: Record<string, number> = {
  first: 1, one: 1, "1st": 1, second: 2, two: 2, "2nd": 2, third: 3, three: 3, "3rd": 3, fourth: 4, four: 4,
  "4th": 4, fifth: 5, five: 5, "5th": 5, sixth: 6, six: 6, last: -1,
};

const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9 ]+/g, " ").replace(/\s+/g, " ").trim();

/** Match a spoken answer to an option: "the second one", "number 2", "YouTube", "change or add code". */
export function matchChoice(text: string, options: FlowOption[]): string | null {
  const usable = options.filter((o) => o.available);
  const t = norm(text);
  if (!t) return null;
  const byName = usable.filter((o) => {
    const label = norm(o.label);
    return t === label || t === norm(o.value) || (label.length > 2 && t.includes(label)) ||
      (t.length > 2 && label.startsWith(t));
  });
  if (byName.length === 1) return byName[0].value;
  const num = t.match(/\b(?:number|option|the)?\s*(\d)\b/);
  let n = num ? Number(num[1]) : 0;
  if (!n) {
    const w = t.split(" ").find((x) => x in ORDINALS);
    n = w ? ORDINALS[w] : 0;
  }
  if (n === -1) n = usable.length;
  return n >= 1 && n <= usable.length ? usable[n - 1].value : null;
}

export interface SearchResult {
  title: string;
  url: string;
  channel?: string;
  length?: string;
}

/** Results of the flow's last search, for the "pick one" list (page text is untrusted: shown, never acted on). */
export function resultsOf(job: Job | undefined): SearchResult[] {
  const step = job?.steps.slice().reverse().find((s) => s.tool === "web_search" && s.result.ok);
  const r = step?.result.data?.results;
  return Array.isArray(r) ? (r as SearchResult[]).filter((x) => x && typeof x.title === "string") : [];
}

/** Controls / follow-ups that only apply to some answers (e.g. Word-only dictation and edits). */
export function applies(when: { stage: string; values: string[] } | null | undefined, answers: Answers): boolean {
  return !when || when.values.includes(answers[when.stage] ?? "");
}
