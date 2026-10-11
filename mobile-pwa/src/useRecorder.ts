import { useCallback, useEffect, useRef, useState } from "react";

export type MicState = "idle" | "recording" | "denied" | "unsupported" | "insecure";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** Push-to-talk and Tap-to-talk recorder with Web Audio real-time volume detection. */
export function useRecorder(onAudio: (blob: Blob) => void) {
  const [state, setState] = useState<MicState>(() => {
    if (!window.isSecureContext) return "insecure";
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") return "unsupported";
    return "idle";
  });

  const [volume, setVolume] = useState<number>(0);
  const [mode, setMode] = useState<"hold" | "tap">("hold");

  const recRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const animFrameRef = useRef<number | null>(null);

  const cleanupAudioAnalysis = useCallback(() => {
    if (animFrameRef.current) {
      cancelAnimationFrame(animFrameRef.current);
      animFrameRef.current = null;
    }
    if (audioCtxRef.current && audioCtxRef.current.state !== "closed") {
      audioCtxRef.current.close().catch(() => {});
      audioCtxRef.current = null;
    }
    setVolume(0);
  }, []);

  const setupAudioAnalysis = useCallback((stream: MediaStream) => {
    try {
      const AudioCtx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AudioCtx) return;
      const ctx = new AudioCtx();
      audioCtxRef.current = ctx;
      const src = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 64;
      analyser.smoothingTimeConstant = 0.5;
      src.connect(analyser);

      const dataArray = new Uint8Array(analyser.frequencyBinCount);
      const tick = () => {
        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < dataArray.length; i++) {
          sum += dataArray[i];
        }
        const avg = sum / dataArray.length;
        // Normalize roughly to 0..1
        const norm = Math.min(1, Math.max(0, avg / 128));
        setVolume(norm);
        animFrameRef.current = requestAnimationFrame(tick);
      };
      tick();
    } catch {
      // AudioContext unavailable or restricted, fallback to volume 0
    }
  }, []);

  const start = useCallback(async () => {
    if (state === "recording" || state === "insecure" || state === "unsupported") return;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
    } catch {
      setState("denied");
      return;
    }

    if (navigator.vibrate) {
      try {
        navigator.vibrate(30);
      } catch {
        /* ignore */
      }
    }

    streamRef.current = stream;
    setupAudioAnalysis(stream);

    const mimeType = MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunks.current = [];

    rec.ondataavailable = (e) => {
      if (e.data.size) chunks.current.push(e.data);
    };

    rec.onstop = () => {
      cleanupAudioAnalysis();
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
      }
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      setState("idle");

      if (navigator.vibrate) {
        try {
          navigator.vibrate(20);
        } catch {
          /* ignore */
        }
      }

      // Ignore accidental taps (< 350 ms) instead of sending silence
      if (Date.now() - startedAt.current >= 350 && blob.size > 0) {
        onAudio(blob);
      }
    };

    recRef.current = rec;
    startedAt.current = Date.now();
    rec.start();
    setState("recording");
  }, [state, onAudio, setupAudioAnalysis, cleanupAudioAnalysis]);

  const stop = useCallback(() => {
    if (recRef.current?.state === "recording") {
      recRef.current.stop();
    }
    recRef.current = null;
  }, []);

  const toggle = useCallback(() => {
    if (state === "recording") {
      stop();
    } else {
      void start();
    }
  }, [state, start, stop]);

  useEffect(() => {
    return () => {
      cleanupAudioAnalysis();
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, [cleanupAudioAnalysis]);

  return {
    state,
    start,
    stop,
    toggle,
    volume,
    mode,
    setMode,
  };
}
