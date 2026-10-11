/**
 * Hands-free mode (Phase 4): energy-based voice activity detection on the phone.
 * Only speech segments leave the device — never a continuous stream — and PC1 drops any segment that
 * does not start with the wake word.
 */

export interface VadOptions {
  sampleRate: number;
  /** Speech must stay above the threshold this long to start a segment. */
  startMs?: number;
  /** A segment ends after this much silence. */
  endSilenceMs?: number;
  /** Audio kept from just before speech started (so the first syllable isn't cut). */
  preRollMs?: number;
  minSpeechMs?: number;
  maxSegmentMs?: number;
  /** Absolute floor for the speech threshold (RMS, 0..1). */
  minThreshold?: number;
}

export function rms(frame: Float32Array): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i];
  return Math.sqrt(sum / Math.max(1, frame.length));
}

/** Feed fixed-size frames; returns a finished speech segment (raw samples) or null. */
export class SegmentDetector {
  private noise = 0.005;
  private pre: Float32Array[] = [];
  private seg: Float32Array[] = [];
  private voicedMs = 0;
  private aboveMs = 0;
  private silenceMs = 0;
  private inSpeech = false;
  private readonly o: Required<VadOptions>;

  constructor(opts: VadOptions) {
    this.o = {
      startMs: 120,
      endSilenceMs: 750,
      preRollMs: 350,
      minSpeechMs: 300,
      maxSegmentMs: 8000,
      minThreshold: 0.012,
      ...opts,
    };
  }

  get speaking(): boolean {
    return this.inSpeech;
  }

  threshold(): number {
    return Math.max(this.o.minThreshold, this.noise * 3.5);
  }

  feed(frame: Float32Array): Float32Array | null {
    const ms = (frame.length / this.o.sampleRate) * 1000;
    const level = rms(frame);
    const voiced = level > this.threshold();
    if (!this.inSpeech) {
      if (!voiced) this.noise = this.noise * 0.95 + level * 0.05; // adapt to the room while quiet
      this.pre.push(frame);
      while (this.pre.length * ms > this.o.preRollMs + this.o.startMs) this.pre.shift();
      this.aboveMs = voiced ? this.aboveMs + ms : 0;
      if (this.aboveMs >= this.o.startMs) {
        this.inSpeech = true;
        this.seg = [...this.pre];
        this.pre = [];
        this.voicedMs = this.aboveMs;
        this.silenceMs = 0;
      }
      return null;
    }
    this.seg.push(frame);
    if (voiced) {
      this.voicedMs += ms;
      this.silenceMs = 0;
    } else {
      this.silenceMs += ms;
    }
    const totalMs = this.seg.length * ms;
    if (this.silenceMs >= this.o.endSilenceMs || totalMs >= this.o.maxSegmentMs) {
      const out = this.voicedMs >= this.o.minSpeechMs ? concat(this.seg) : null;
      this.reset();
      return out;
    }
    return null;
  }

  reset(): void {
    this.inSpeech = false;
    this.seg = [];
    this.pre = [];
    this.voicedMs = this.aboveMs = this.silenceMs = 0;
  }
}

export function concat(parts: Float32Array[]): Float32Array {
  const out = new Float32Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) {
    out.set(p, o);
    o += p.length;
  }
  return out;
}

/** Average-decimate to the target rate (Whisper wants 16 kHz; plenty for speech). */
export function downsample(input: Float32Array, from: number, to = 16000): Float32Array {
  if (from === to) return input;
  const ratio = from / to;
  const out = new Float32Array(Math.floor(input.length / ratio));
  for (let i = 0; i < out.length; i++) {
    const a = Math.floor(i * ratio);
    const b = Math.min(input.length, Math.floor((i + 1) * ratio));
    let s = 0;
    for (let j = a; j < b; j++) s += input[j];
    out[i] = s / Math.max(1, b - a);
  }
  return out;
}

/** 16-bit PCM mono WAV. */
export function encodeWav(samples: Float32Array, sampleRate: number): Blob {
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const v = new DataView(buf);
  const str = (o: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i));
  };
  str(0, "RIFF");
  v.setUint32(4, 36 + samples.length * 2, true);
  str(8, "WAVE");
  str(12, "fmt ");
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  str(36, "data");
  v.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([buf], { type: "audio/wav" });
}

/** Short spoken version of a result for text-to-speech (no long hints, no quotes). */
export function spokenText(text: string, max = 220): string {
  const t = text
    .replace(/\s*Say “[^”]*”( or “[^”]*”)?\.?/g, "")
    .replace(/[“”"`*_]/g, "")
    .replace(/\s+/g, " ")
    .trim();
  return t.length > max ? t.slice(0, max).replace(/\s+\S*$/, "") + "…" : t;
}
