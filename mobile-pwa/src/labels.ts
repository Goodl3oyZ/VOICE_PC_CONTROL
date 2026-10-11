import type { Job, JobState } from "./api";

export const STATE_TH: Record<JobState, string> = {
  created: "รับคำสั่งแล้ว",
  transcribing: "กำลังถอดเสียง…",
  planning: "กำลังวางแผน…",
  clarifying: "รอคำตอบจากคุณ",
  routing: "กำลังตรวจสิทธิ์…",
  awaiting_confirm: "รอการยืนยันความปลอดภัย",
  dispatching: "กำลังส่งไป PC2…",
  running: "PC2 กำลังทำงาน…",
  verifying: "กำลังตรวจผล…",
  done: "เสร็จสิ้นแล้ว",
  failed: "ไม่สำเร็จ",
  cancelled: "ยกเลิกแล้ว",
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

export const STATE_DESC_TH: Record<JobState, string> = {
  created: "ระบบบันทึกคำสั่งและกำลังเข้าสู่คิวประมวลผล",
  transcribing: "แปลงเสียงพูดเป็นข้อความด้วยโมเดล Whisper",
  planning: "AI กำลังตีความหมายและเลือกคำสั่งหรือเครื่องมือที่เหมาะสม",
  clarifying: "ระบบต้องการข้อมูลเพิ่มเติมเพื่อความถูกต้อง กรุณาตอบกลับด้านล่าง",
  routing: "ตรวจสอบสิทธิ์ความปลอดภัยและระดับความเสี่ยงของคำสั่ง",
  awaiting_confirm: "คำสั่งนี้มีผลกระทบต่อระบบ กรุณาตรวจสอบรายละเอียดก่อนอนุมัติ",
  dispatching: "ส่งคำสั่งผ่านช่องทางความปลอดภัยไปยังเครื่อง PC เป้าหมาย",
  running: "เครื่อง PC กำลังดำเนินการตามคำสั่ง",
  verifying: "ตรวจสอบผลการดำเนินการว่าสำเร็จถูกต้องหรือไม่",
  done: "การทำงานเสร็จสมบูรณ์เรียบร้อย",
  failed: "เกิดข้อผิดพลาดในการประมวลผลหรือการสั่งการ",
  cancelled: "คำสั่งถูกยกเลิกตามคำขอหรือหมดเวลา",
};

export const TERMINAL: ReadonlySet<JobState> = new Set(["done", "failed", "cancelled"]);

export function isActive(job: Job): boolean {
  return !TERMINAL.has(job.state);
}

const RISK_TH = [
  "ระดับ 0: อ่านอย่างเดียว (ปลอดภัย)",
  "ระดับ 1: เปิดแอปพลิเคชันทั่วไป",
  "ระดับ 2: แก้ไขในขอบเขตที่จำกัด",
  "ระดับ 3: มีผลภายนอกหรือย้อนคืนยาก",
  "ระดับ 4: คำสั่งระดับสูง / ห้ามโดยค่าเริ่มต้น",
];

export const riskLabel = (risk: number) => RISK_TH[risk] ?? `ระดับความเสี่ยงที่ ${risk}`;

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

export function formatDuration(ms?: number): string {
  if (ms === undefined || ms === null) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} วินาที`;
}

export function formatTime(timestampSeconds: number): string {
  try {
    return new Date(timestampSeconds * 1000).toLocaleTimeString("th-TH", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "";
  }
}
