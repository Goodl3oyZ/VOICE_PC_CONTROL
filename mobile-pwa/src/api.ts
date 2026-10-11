// Thin client for the PC1 orchestrator API (doc appendix A.2).

export type JobState =
  | "created" | "transcribing" | "planning" | "clarifying" | "routing" | "awaiting_confirm"
  | "dispatching" | "running" | "verifying" | "done" | "failed" | "cancelled";

export interface Pending {
  tool: string;
  arguments: Record<string, unknown>;
  args_hash: string;
  risk: number;
  reason: string;
  expires_at: number;
}

export interface Job {
  id: string;
  state: JobState;
  source: "text" | "audio";
  created_at: number;
  text: string;
  normalized: string;
  stt_confidence: number | null;
  question: string | null;
  pending: Pending | null;
  steps: {
    tool: string;
    arguments: Record<string, unknown>;
    result: { ok: boolean; verified: boolean; data?: Record<string, unknown>; error?: string | null };
  }[];
  summary: string;
  error: string | null;
  outcome: string | null;
  timings_ms: Record<string, number>;
}

export type ServerEvent =
  | { type: "job.update"; job: Job }
  | { type: "pc2.status"; online: boolean; status: Record<string, unknown> };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export interface Capabilities {
  language: string;
  english_only: boolean;
  groups: { id: string; title: string; hint: string; examples: string[] }[];
  apps: string[];
  sites: string[];
  refused: string[];
}

export interface AuthState {
  authenticated: boolean;
  email: string | null;
  paired: boolean;
  google_enabled: boolean;
}

/**
 * Auth lives in HttpOnly cookies set by PC1 (Google session + paired-device token), so JavaScript never
 * sees a secret. Every request carries X-Requested-With, which the server requires as CSRF protection.
 */
export class Api {
  private async req<T>(method: string, path: string, body?: BodyInit, json = true): Promise<T> {
    const headers: Record<string, string> = { "X-Requested-With": "voicepc" };
    if (body !== undefined && json) headers["Content-Type"] = "application/json";
    const res = await fetch(path, { method, headers, body, credentials: "same-origin" });
    if (!res.ok) {
      let detail = res.statusText;
      try {
        detail = (await res.json()).detail ?? detail;
      } catch {
        /* not JSON */
      }
      throw new ApiError(res.status, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.json() as Promise<T>;
  }

  sendText = (text: string) => this.req<Job>("POST", "/command", JSON.stringify({ text }));

  sendAudio = (blob: Blob) => {
    const form = new FormData();
    const ext = blob.type.includes("mp4") ? "m4a" : "webm";
    form.append("audio", blob, `command.${ext}`);
    return this.req<Job>("POST", "/command/audio", form, false);
  };

  cancel = (id: string) => this.req<Job>("POST", `/jobs/${encodeURIComponent(id)}/cancel`);
  reply = (id: string, text: string) => this.req<Job>("POST", `/jobs/${encodeURIComponent(id)}/reply`, JSON.stringify({ text }));
  confirm = (id: string, approve: boolean, args_hash: string) =>
    this.req<Job>("POST", `/confirm/${encodeURIComponent(id)}`, JSON.stringify({ approve, args_hash }));
  stop = () => this.req<{ cancelled: string[]; pc2_stopped: boolean }>("POST", "/stop");
  jobs = (limit = 50) => this.req<Job[]>("GET", `/jobs?limit=${limit}`);
  status = () => this.req<{ pc2_online: boolean; pc2: Record<string, unknown> }>("GET", "/status");

  me = () => this.req<AuthState>("GET", "/auth/me");
  capabilities = () => this.req<Capabilities>("GET", "/capabilities");
  pair = (key: string, label: string) =>
    this.req<{ paired: boolean; device: string }>("POST", "/auth/pair", JSON.stringify({ key, label }));
  logout = () => this.req<{ ok: boolean }>("POST", "/auth/logout");
  unpair = () => this.req<{ ok: boolean }>("POST", "/auth/unpair");

  eventsUrl() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${location.host}/events`; // cookies + Origin authenticate the socket
  }
}
