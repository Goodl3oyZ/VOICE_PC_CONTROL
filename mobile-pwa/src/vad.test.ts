import { describe, expect, it } from "vitest";
import { SegmentDetector, downsample, encodeWav, spokenText } from "./vad";

const SR = 16000;
const FRAME = 320; // 20 ms
const tone = (amp: number) => {
  const f = new Float32Array(FRAME);
  for (let i = 0; i < FRAME; i++) f[i] = amp * Math.sin((2 * Math.PI * 220 * i) / SR);
  return f;
};
const quiet = () => tone(0.001);
const loud = () => tone(0.3);

function run(det: SegmentDetector, frames: Float32Array[]) {
  const out: Float32Array[] = [];
  for (const f of frames) {
    const seg = det.feed(f);
    if (seg) out.push(seg);
  }
  return out;
}

describe("SegmentDetector", () => {
  it("cuts one segment per utterance, with pre-roll", () => {
    const det = new SegmentDetector({ sampleRate: SR });
    const frames = [
      ...Array.from({ length: 50 }, quiet), // 1 s room noise
      ...Array.from({ length: 40 }, loud), // 0.8 s speech
      ...Array.from({ length: 50 }, quiet), // 1 s silence -> segment ends
    ];
    const segs = run(det, frames);
    expect(segs).toHaveLength(1);
    const ms = (segs[0].length / SR) * 1000;
    expect(ms).toBeGreaterThan(800 + 300); // speech + pre-roll + trailing silence
    expect(ms).toBeLessThan(2200);
  });

  it("ignores clicks shorter than the start window and stays quiet in a noisy-but-steady room", () => {
    const det = new SegmentDetector({ sampleRate: SR });
    const click = [loud(), loud()]; // 40 ms
    expect(run(det, [...Array.from({ length: 50 }, quiet), ...click, ...Array.from({ length: 80 }, quiet)])).toHaveLength(0);
    const hum = () => tone(0.02); // steady fan noise: the floor adapts
    const det2 = new SegmentDetector({ sampleRate: SR, minThreshold: 0.001 });
    expect(run(det2, Array.from({ length: 300 }, hum))).toHaveLength(0);
  });

  it("caps very long speech", () => {
    const det = new SegmentDetector({ sampleRate: SR, maxSegmentMs: 2000 });
    const segs = run(det, [...Array.from({ length: 20 }, quiet), ...Array.from({ length: 300 }, loud)]);
    expect(segs.length).toBeGreaterThanOrEqual(2);
  });
});

describe("audio encoding", () => {
  it("downsamples 48k to 16k", () => {
    expect(downsample(new Float32Array(4800), 48000).length).toBe(1600);
  });

  it("writes a valid 16 kHz mono WAV header", async () => {
    const blob = encodeWav(new Float32Array(1600), 16000);
    const v = new DataView(await blob.arrayBuffer());
    expect(blob.type).toBe("audio/wav");
    expect(String.fromCharCode(v.getUint8(0), v.getUint8(1), v.getUint8(2), v.getUint8(3))).toBe("RIFF");
    expect(v.getUint32(24, true)).toBe(16000);
    expect(v.getUint32(40, true)).toBe(3200);
  });
});

describe("spokenText", () => {
  it("drops the follow-up hints and quotes", () => {
    expect(
      spokenText("Added f. 1 edit(s) on branch ai/x (calc.py); tests PASSED. Say “show the diff for demo” or “revert the changes in demo”."),
    ).toBe("Added f. 1 edit(s) on branch ai/x (calc.py); tests PASSED.");
    expect(spokenText("Opened “Chrome”")).toBe("Opened Chrome");
  });
});
