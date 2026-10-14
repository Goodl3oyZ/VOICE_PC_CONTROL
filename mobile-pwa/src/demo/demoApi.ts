import { Api, type AuthState, type Capabilities, type FlowDef, type Job, type ServerEvent } from "../api";
import data from "./data.json";

/** /demo: anyone can look around. This client never calls PC1, so nothing can reach the real PC. */
export function isDemo(): boolean {
  return location.pathname.replace(/\/+$/, "") === "/demo";
}

type Fake = { tool: string; args: Record<string, unknown>; summary: string; approve?: string; results?: boolean };

const RULES: [RegExp, (m: RegExpMatchArray) => Fake][] = [
  [/^(next song|skip|เพลงถัดไป)/i, () => ({ tool: "media_control", args: { action: "next" }, summary: "Skipped to the next song" })],
  [/^(pause|play\/pause|resume|หยุดเพลง)/i, () => ({ tool: "media_control", args: { action: "play_pause" }, summary: "Paused the music" })],
  [/^volume up/i, () => ({ tool: "media_control", args: { action: "volume_up", steps: 10 }, summary: "Volume up 20 %" })],
  [/screen/i, () => ({ tool: "describe_screen", args: {}, summary: "Chrome is showing a lofi music mix on YouTube." })],
  [/^(?:play|เล่นเพลง|เปิดเพลง)\s+(.+)/i, (m) => ({ tool: "youtube_play", args: { query: m[1] }, summary: `Playing “${m[1]}” on YouTube` })],
  [/^(?:search(?: for)?|ค้นหา)\s+(.+)/i, (m) => ({ tool: "web_search", args: { query: m[1], site: "web" }, summary: `Found 5 results for “${m[1]}”`, results: true })],
  [/\b(post|stream|send|comment|like|follow)\b/i, () => ({ tool: "social_act", args: {}, summary: "Done", approve: "This is public: it needs your approval first" })],
  [/^open (.+)/i, (m) => ({ tool: "open_app", args: { app: m[1] }, summary: `Opened ${m[1]}` })],
];

const SAMPLE_RESULTS = ["Lofi hip hop radio: beats to relax/study to", "Chill lofi mix (3 hours)", "Coffee shop lofi",
  "Rainy night lofi", "Lofi for coding"].map((title, i) => ({ title, url: `https://www.youtube.com/watch?v=demo${i}` }));

const SAID = ["Play lofi hip hop", "Next song", "Search for weather in Bangkok", "What's on the screen?"];

function guess(text: string): Fake {
  for (const [re, f] of RULES) {
    const m = text.trim().match(re);
    if (m) return f(m);
  }
  return { tool: "plan", args: {}, summary: `Done: “${text}”` };
}

export class DemoApi extends Api {
  readonly demo = true;
  private jobsList: Job[] = [];
  private listeners = new Set<(ev: ServerEvent) => void>();
  private n = 0;
  private said = 0;

  constructor() {
    super();
    const now = Date.now() / 1000;
    this.jobsList = [
      this.job("Next song", now - 40, "Skipped to the next song", "media_control"),
      this.job("Open Chrome", now - 300, "Opened Chrome", "open_app"),
    ];
  }

  private job(text: string, at: number, summary: string, tool: string): Job {
    return {
      id: `demo-${++this.n}`, state: "done", source: "text", created_at: at, text, normalized: text.toLowerCase(),
      stt_confidence: null, question: null, pending: null, error: null, outcome: "done_verified", planner: "shortcut",
      timings_ms: { pc2: 400 + Math.round(Math.random() * 900) }, summary,
      steps: [{ tool, arguments: {}, result: { ok: true, verified: true } }],
    };
  }

  private emit(job: Job) {
    this.jobsList = [job, ...this.jobsList.filter((j) => j.id !== job.id)].slice(0, 30);
    for (const l of this.listeners) l({ type: "job.update", job: { ...job } });
  }

  private find(id: string): Job {
    const j = this.jobsList.find((x) => x.id === id);
    if (!j) throw new Error("unknown job");
    return j;
  }

  /** Planning -> running -> done (or waiting for approval), like the real thing but only in this page. */
  private start(text: string, flow: string | null = null): Job {
    const f = guess(text);
    const job: Job = { ...this.job(text, Date.now() / 1000, "", f.tool), state: "planning", steps: [], outcome: null, flow };
    this.emit(job);
    window.setTimeout(() => {
      if (f.approve) {
        this.emit({ ...this.find(job.id), state: "awaiting_confirm",
          pending: { tool: f.tool, arguments: { text }, args_hash: "demo", risk: 3, reason: f.approve, expires_at: Date.now() / 1000 + 120 } });
        return;
      }
      this.emit({ ...this.find(job.id), state: "running" });
      window.setTimeout(() => this.finish(job.id, f), 900);
    }, 600);
    return job;
  }

  private finish(id: string, f: Fake) {
    const j = this.find(id);
    if (j.state === "cancelled") return;
    this.emit({ ...j, state: "done", outcome: "done_verified", pending: null, summary: f.summary,
      steps: [{ tool: f.tool, arguments: f.args, result: { ok: true, verified: true, data: f.results ? { results: SAMPLE_RESULTS } : {} } }] });
  }

  listen(on: (ev: ServerEvent) => void): () => void {
    this.listeners.add(on);
    on({ type: "pc2.status", online: true, status: this.pcStatus() });
    return () => this.listeners.delete(on);
  }

  private pcStatus(): Record<string, unknown> {
    return { hostname: "DEMO-PC", cpu_percent: 12, ram_percent: 41, chrome_connected: true, active_window: "YouTube - Google Chrome" };
  }

  me = async (): Promise<AuthState> => ({ authenticated: true, email: null, paired: true, google_enabled: true });
  status = async () => ({ pc2_online: true, pc2: this.pcStatus() });
  jobs = async () => this.jobsList.map((j) => ({ ...j }));
  capabilities = async () => data.capabilities as unknown as Capabilities;
  flows = async () => data.flows as unknown as FlowDef[];

  sendText = async (text: string) => this.start(text);
  transcribe = async () => {
    await new Promise((r) => window.setTimeout(r, 700));
    return { text: SAID[this.said++ % SAID.length], confidence: 0.92 };
  };
  runFlow = async (id: string, answers: Record<string, string>) => {
    const flow = (data.flows as unknown as FlowDef[]).find((f) => f.id === id);
    const query = answers.query || answers.request || "";
    const text = id === "youtube" && answers.what === "search" ? `search ${query} on youtube`
      : id === "youtube" || id === "music" ? `play ${query || "lofi"}`
        : id === "search" ? `search ${query}` : `${flow?.title ?? id}: ${Object.values(answers).join(" · ")}`;
    const job = this.start(text, id);
    if (flow?.pick_results) job.steps = [];
    return { job };
  };
  flowControl = async (id: string, index: number) => {
    const flow = (data.flows as unknown as FlowDef[]).find((f) => f.id === id);
    return this.start(flow?.controls[index]?.label ?? "Control", id);
  };
  flowFollowup = async (id: string, text: string) => this.start(text, id);
  reply = async (id: string, text: string) => {
    const j = this.find(id);
    this.emit({ ...j, state: "running", question: null, clarify_kind: null });
    window.setTimeout(() => this.finish(id, guess(text)), 800);
    return this.find(id);
  };
  confirm = async (id: string, approve: boolean) => {
    const j = this.find(id);
    if (!approve) {
      this.emit({ ...j, state: "cancelled", pending: null, outcome: "cancelled", error: "Cancelled by you" });
    } else {
      this.emit({ ...j, state: "running", pending: null });
      window.setTimeout(() => this.finish(id, { ...guess(j.text), summary: "Approved and done" }), 800);
    }
    return this.find(id);
  };
  cancel = async (id: string) => {
    this.emit({ ...this.find(id), state: "cancelled", outcome: "cancelled", error: "Stopped by you" });
    return this.find(id);
  };
  stop = async () => {
    for (const j of this.jobsList) if (!["done", "failed", "cancelled"].includes(j.state)) await this.cancel(j.id);
    return { cancelled: [], pc2_stopped: true };
  };
  logout = async () => {
    location.href = "/";
    return { ok: true };
  };
  unpair = this.logout;
}
