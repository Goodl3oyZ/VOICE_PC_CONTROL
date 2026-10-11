import type { Job, JobState } from "./api";

export const STATE_TH: Record<JobState, string> = {
  created: "รับคำสั่งแล้ว",
  transcribing: "กำลังถอดเสียง…",
  planning: "กำลังวางแผน…",
  clarifying: "รอคำตอบจากคุณ",
  routing: "กำลังตรวจสิทธิ์…",
  awaiting_confirm: "รอการยืนยัน",
  dispatching: "กำลังส่งไป PC2…",
  running: "PC2 กำลังทำงาน…",
  verifying: "กำลังตรวจผล…",
  done: "เสร็จแล้ว",
  failed: "ไม่สำเร็จ",
  cancelled: "ยกเลิกแล้ว",
};

export const TERMINAL: ReadonlySet<JobState> = new Set(["done", "failed", "cancelled"]);

export function isActive(job: Job): boolean {
  return !TERMINAL.has(job.state);
}

const RISK_TH = ["อ่านอย่างเดียว", "เปิดแอป", "แก้ไขในขอบเขต", "มีผลภายนอก/ย้อนยาก", "ห้ามโดยค่าเริ่มต้น"];
export const riskLabel = (risk: number) => RISK_TH[risk] ?? `ระดับ ${risk}`;

/** Confirmation card text is built from the real tool + arguments, never from LLM prose (§20.5). */
export function describeCall(tool: string, args: Record<string, unknown>): string[] {
  return [`เครื่องมือ: ${tool}`, ...Object.entries(args).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)}`)];
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
