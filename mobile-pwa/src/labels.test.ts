import { describe, expect, it } from "vitest";
import type { Job } from "./api";
import {
  STATE_LABEL,
  codeContext,
  dayLabel,
  jobHeadline,
  jobKind,
  diffLineKind,
  STATE_DESC,
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
      "Tool: send_message",
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
    expect(formatDuration(1200)).toBe("1.20 s");
    expect(formatDuration(3500)).toBe("3.50 s");
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
      expect(STATE_LABEL[s]).toBeDefined();
      expect(STATE_DESC[s]).toBeDefined();
    }
  });

  it("formats risk levels accurately", () => {
    expect(riskLabel(0)).toContain("Level 0");
    expect(riskLabel(1)).toContain("Level 1");
    expect(riskLabel(4)).toContain("Level 4");
    expect(riskLabel(99)).toContain("Risk level 99");
  });
});

describe("codeContext (Phase 3)", () => {
  const job = (steps: Job["steps"]) => ({ steps }) as unknown as Job;
  const step = (tool: string, data: Record<string, unknown> = {}, ok = true) => ({
    tool,
    arguments: { project: "demo" },
    result: { ok, verified: ok, data },
  });

  it("is null for non-coding jobs and after a revert", () => {
    expect(codeContext(job([{ tool: "open_app", arguments: { app: "notepad" }, result: { ok: true, verified: true } }]))).toBeNull();
    expect(codeContext(job([step("edit_file"), step("revert_changes")]))).toBeNull();
  });

  it("offers revert after an edit and shows the diff when present", () => {
    const c = codeContext(job([step("read_file"), step("edit_file"), step("run_tests", { passed: true })]));
    expect(c).toEqual({ project: "demo", diff: null, files: [], hasChanges: true });
    const d = codeContext(job([step("git_diff", { files: ["calc.py"], diff: "+x\n-y" })]));
    expect(d?.diff).toBe("+x\n-y");
    expect(d?.hasChanges).toBe(true);
  });

  it("classifies diff lines", () => {
    expect(["+++ b/a", "@@ -1 +1 @@", "+new", "-old", " same"].map(diffLineKind)).toEqual([
      "meta", "hunk", "add", "del", "ctx",
    ]);
  });
});

describe("activity timeline", () => {
  const full = (over: Partial<Job>) =>
    ({ id: "x", state: "done", text: "play Drake", summary: "", error: null, question: null, pending: null, steps: [], ...over }) as Job;
  const step = (tool: string, args: Record<string, unknown> = {}) => ({ tool, arguments: args, result: { ok: true, verified: true } });

  it("says what happened, not the tool", () => {
    expect(jobHeadline(full({ summary: "Playing Drake on YouTube" }))).toBe("Playing Drake on YouTube");
    expect(jobHeadline(full({ state: "failed", error: "Chrome isn't open" }))).toBe("Chrome isn't open");
    expect(jobHeadline(full({ state: "cancelled" }))).toBe("Cancelled");
    expect(jobHeadline(full({ state: "running" }))).toBe(STATE_LABEL.running);
  });

  it("picks an icon from the last step", () => {
    expect(jobKind(full({ steps: [step("media_control", { action: "next" })] }))).toBe("skip");
    expect(jobKind(full({ steps: [step("media_control", { action: "mute" })] }))).toBe("volume");
    expect(jobKind(full({ steps: [step("web_search"), step("open_result")] }))).toBe("search");
    expect(jobKind(full({ steps: [step("social_open")] }))).toBe("app");
    expect(jobKind(full({ steps: [step("edit_file")] }))).toBe("code");
    expect(jobKind(full({}))).toBe("chat");
  });

  it("groups by day", () => {
    const now = new Date(2026, 9, 14, 10, 0);
    const at = (d: Date) => d.getTime() / 1000;
    expect(dayLabel(at(new Date(2026, 9, 14, 0, 5)), now)).toBe("Today");
    expect(dayLabel(at(new Date(2026, 9, 13, 23, 50)), now)).toBe("Yesterday");
    expect(dayLabel(at(new Date(2026, 9, 10, 12, 0)), now)).toMatch(/10 Oct/);
  });
});
