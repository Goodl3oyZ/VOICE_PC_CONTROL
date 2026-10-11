import { describe, expect, it } from "vitest";
import type { Job } from "./api";
import { describeCall, isActive, secondsLeft, upsertJob } from "./labels";

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
    expect(isActive(job("a", "running"))).toBe(true);
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
  });
});
