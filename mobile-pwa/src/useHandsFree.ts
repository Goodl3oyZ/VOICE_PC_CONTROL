import { useCallback, useEffect, useRef, useState } from "react";
import type { Job, WakeResult } from "./api";
import { SegmentDetector, downsample, encodeWav } from "./vad";

export type HandsFreeState = "off" | "starting" | "waiting" | "hearing" | "sending" | "armed" | "error";

const ARMED_MS = 8000; // after a bare "computer", the next sentence needs no wake word

/**
 * Hands-free listening (Phase 4). The mic stays open while this is on and the app is visible; speech
 * segments are sent to PC1, which keeps only wake-word commands. `paused()` lets the app mute it while the
 * phone is speaking (so it never hears itself) or push-to-talk is recording.
 */
export function useHandsFree(
  send: (wav: Blob, armed: boolean) => Promise<WakeResult>,
  onJob: (job: Job) => void,
  paused: () => boolean,
) {
  const [state, setState] = useState<HandsFreeState>("off");
  const [error, setError] = useState<string | null>(null);
  const armedUntil = useRef(0);
  const cleanup = useRef<(() => void) | null>(null);
  const cb = useRef({ send, onJob, paused });
  cb.current = { send, onJob, paused };

  const stop = useCallback(() => {
    cleanup.current?.();
    cleanup.current = null;
    armedUntil.current = 0;
    setState("off");
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setState("starting");
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      });
      const AudioCtx =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      const ctx = new AudioCtx();
      const src = ctx.createMediaStreamSource(stream);
      // ScriptProcessor is deprecated but universally available (incl. iOS Safari) and simple enough here.
      const proc = ctx.createScriptProcessor(2048, 1, 1);
      const det = new SegmentDetector({ sampleRate: ctx.sampleRate });
      let sending = false;
      let wakeLock: { release: () => Promise<void> } | null = null;
      try {
        // Mobile browsers stop the mic when the screen sleeps; keep it on while hands-free is active.
        wakeLock = await (navigator as unknown as { wakeLock?: { request: (t: string) => Promise<typeof wakeLock> } })
          .wakeLock?.request("screen") ?? null;
      } catch {
        wakeLock = null;
      }

      proc.onaudioprocess = (e) => {
        if (cb.current.paused() || sending) {
          det.reset();
          return;
        }
        const seg = det.feed(new Float32Array(e.inputBuffer.getChannelData(0)));
        const armed = Date.now() < armedUntil.current;
        if (!seg) {
          setState(det.speaking ? "hearing" : armed ? "armed" : "waiting");
          return;
        }
        sending = true;
        setState("sending");
        const wav = encodeWav(downsample(seg, ctx.sampleRate), 16000);
        cb.current
          .send(wav, armed)
          .then((r) => {
            if (r.status === "listening") {
              armedUntil.current = Date.now() + ARMED_MS;
              beep(ctx);
            } else if (r.status === "job") {
              armedUntil.current = 0;
              cb.current.onJob(r.job);
            }
          })
          .catch((err) => setError(err instanceof Error ? err.message : String(err)))
          .finally(() => {
            sending = false;
          });
      };
      src.connect(proc);
      proc.connect(ctx.destination); // required for processing to run; output is silence

      cleanup.current = () => {
        proc.onaudioprocess = null;
        src.disconnect();
        proc.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        ctx.close().catch(() => {});
        wakeLock?.release().catch(() => {});
      };
      setState("waiting");
    } catch (e) {
      setError(e instanceof Error && e.name === "NotAllowedError" ? "Microphone permission denied" : String(e));
      setState("error");
    }
  }, []);

  const toggle = useCallback(() => {
    if (cleanup.current) stop();
    else void start();
  }, [start, stop]);

  // Stop listening when the app goes to the background (the browser would cut the mic anyway).
  useEffect(() => {
    const onHide = () => {
      if (document.hidden && cleanup.current) stop();
    };
    document.addEventListener("visibilitychange", onHide);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      cleanup.current?.();
    };
  }, [stop]);

  return { state, error, on: state !== "off" && state !== "error", toggle };
}

function beep(ctx: AudioContext) {
  try {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.frequency.value = 880;
    g.gain.value = 0.08;
    o.connect(g).connect(ctx.destination);
    o.start();
    o.stop(ctx.currentTime + 0.12);
  } catch {
    /* a missing beep is not worth failing over */
  }
}
