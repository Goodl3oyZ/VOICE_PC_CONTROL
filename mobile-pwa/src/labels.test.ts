import { describe, expect, it } from "vitest";
import type { Job } from "./api";
import {
  STATE_TH,
  STATE_DESC_TH,
  describeCall,
  formatDuration,
  formatTime,
  isActive,
  riskLabel,
  secondsLeft,
  upsertJob,
} from "./labels";

const job = (id: string, state: Job["state"] = "done") => ({ id, state }) as Job;

describe("labels", () => {
  it("upserts newest first and caps at 50", () => {
    let list: Job[] = [];
    for (let i = 0; i < 60; i++) list = upsertJob(list, job(`j${i}`));
    expect(list).toHaveLength(50);
    expect(list[0].id).toBe("j59");
    list = upsertJob(list, job("j55", "failed"));
    expect(list.find((j) => j.id === "j55")?.state).toBe("failed");
    expect(list).toHaveLength(50);
  });

  it("knows active vs terminal", () => {
    expect(isActive(job("a", "created"))).toBe(true);
    expect(isActive(job("a", "transcribing"))).toBe(true);
    expect(isActive(job("a", "planning"))).toBe(true);
    expect(isActive(job("a", "clarifying"))).toBe(true);
    expect(isActive(job("a", "awaiting_confirm"))).toBe(true);
    expect(isActive(job("a", "running"))).toBe(true);
    expect(isActive(job("a", "verifying"))).toBe(true);

    expect(isActive(job("a", "done"))).toBe(false);
    expect(isActive(job("a", "failed"))).toBe(false);
    expect(isActive(job("a", "cancelled"))).toBe(false);
  });

  it("describes the real call for the confirm card", () => {
    expect(describeCall("send_message", { to: "mom", text: "<b>hi</b>" })).toEqual([
      "เครื่องมือ: send_message",
      "to: mom",
      "text: <b>hi</b>",
    ]);
  });

  it("counts down", () => {
    expect(secondsLeft(100, 40_000)).toBe(60);
    expect(secondsLeft(10, 40_000)).toBe(0);
    expect(secondsLeft(0, 10_000)).toBe(0);
  });

  it("formats durations accurately", () => {
    expect(formatDuration(undefined)).toBe("");
    expect(formatDuration(450)).toBe("450 ms");
    expect(formatDuration(1200)).toBe("1.20 วินาที");
    expect(formatDuration(3500)).toBe("3.50 วินาที");
  });

  it("formats timestamps cleanly", () => {
    const formatted = formatTime(1700000000);
    expect(typeof formatted).toBe("string");
    expect(formatted.length).toBeGreaterThan(0);
  });

  it("maps all states to descriptions and Thai titles", () => {
    const states: Job["state"][] = [
      "created",
      "transcribing",
      "planning",
      "clarifying",
      "routing",
      "awaiting_confirm",
      "dispatching",
      "running",
      "verifying",
      "done",
      "failed",
      "cancelled",
    ];

    for (const s of states) {
      expect(STATE_TH[s]).toBeDefined();
      expect(STATE_DESC_TH[s]).toBeDefined();
    }
  });

  it("formats risk levels accurately", () => {
    expect(riskLabel(0)).toContain("ระดับ 0");
    expect(riskLabel(1)).toContain("ระดับ 1");
    expect(riskLabel(4)).toContain("ระดับ 4");
    expect(riskLabel(99)).toContain("ระดับความเสี่ยงที่ 99");
  });
});
