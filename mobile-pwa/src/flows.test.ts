import { describe, expect, it } from "vitest";
import type { FlowDef, FlowOption, Job } from "./api";
import { activeStages, clearFrom, matchChoice, nextStage, resultsOf, startAnswers, stepInfo } from "./flows";

const opt = (value: string, label: string, available = true): FlowOption => ({ value, label, hint: "", available });

const YT: FlowDef = {
  id: "youtube", title: "YouTube", subtitle: "", icon: "youtube", group: "Watch", available: true, coming: "",
  pick_results: true, controls: [], followup: null,
  stages: [
    { id: "what", kind: "choice", question: "What?", placeholder: "", when: null, default: null,
      options: [opt("play", "Play something now"), opt("search", "Search and pick"), opt("controls", "Control what's playing")] },
    { id: "query", kind: "text", question: "Look for?", placeholder: "", default: null, options: [],
      when: { stage: "what", values: ["play", "search"] } },
  ],
};

const MUSIC: FlowDef = {
  ...YT, id: "music",
  stages: [
    { id: "app", kind: "choice", question: "Which app?", placeholder: "", when: null, default: "youtube",
      options: [opt("youtube", "YouTube"), opt("tiktok", "TikTok", false)] },
    { id: "query", kind: "text", question: "Play what?", placeholder: "", when: null, default: null, options: [] },
  ],
};

describe("wizard stages", () => {
  it("skips stages whose condition does not hold", () => {
    expect(activeStages(YT, { what: "controls" }).map((s) => s.id)).toEqual(["what"]);
    expect(nextStage(YT, { what: "controls" })).toBeNull();
    expect(nextStage(YT, { what: "play" })?.id).toBe("query");
    expect(stepInfo(YT, {})).toEqual({ step: 1, total: 2 });
    expect(stepInfo(YT, { what: "play" })).toEqual({ step: 2, total: 2 });
    expect(stepInfo(YT, { what: "controls" }).total).toBe(1);
  });

  it("pre-fills remembered answers and asks only the rest", () => {
    const a = startAnswers(MUSIC);
    expect(a).toEqual({ app: "youtube" });
    expect(nextStage(MUSIC, a)?.id).toBe("query");
  });

  it("changing an answer clears the answers after it", () => {
    expect(clearFrom(YT, { what: "play", query: "lofi" }, "what")).toEqual({});
    expect(clearFrom(YT, { what: "play", query: "lofi" }, "query")).toEqual({ what: "play" });
  });
});

describe("matchChoice (voice answers)", () => {
  const o = YT.stages[0].options;
  it.each([
    ["Search and pick", "search"], ["search", "search"], ["the second one", "search"], ["number 3", "controls"],
    ["Play something now.", "play"], ["first", "play"], ["the last one", "controls"],
  ])("%s -> %s", (said, value) => {
    expect(matchChoice(said, o)).toBe(value);
  });

  it("never picks an unavailable option or guesses", () => {
    expect(matchChoice("TikTok", MUSIC.stages[0].options)).toBeNull();
    expect(matchChoice("second", MUSIC.stages[0].options)).toBeNull();
    expect(matchChoice("banana", o)).toBeNull();
    expect(matchChoice("", o)).toBeNull();
  });
});

it("reads search results from the job's last web_search", () => {
  const job = {
    steps: [{ tool: "web_search", arguments: {}, result: { ok: true, verified: true,
      data: { results: [{ title: "Lofi", url: "https://youtube.com/x" }, null] } } }],
  } as unknown as Job;
  expect(resultsOf(job)).toEqual([{ title: "Lofi", url: "https://youtube.com/x" }]);
  expect(resultsOf(undefined)).toEqual([]);
});

it("Word-only controls and dictation apply only when Word was chosen", async () => {
  const { applies } = await import("./flows");
  const w = { stage: "app", values: ["word"] };
  expect(applies(w, { app: "word" })).toBe(true);
  expect(applies(w, { app: "excel" })).toBe(false);
  expect(applies(null, {})).toBe(true);
});
