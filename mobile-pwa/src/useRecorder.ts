import { useCallback, useRef, useState } from "react";

export type MicState = "idle" | "recording" | "denied" | "unsupported" | "insecure";

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

/** Push-to-talk recorder (MediaRecorder). Mobile browsers only allow the mic over HTTPS (§3.5). */
export function useRecorder(onAudio: (blob: Blob) => void) {
  const [state, setState] = useState<MicState>(() => {
    if (!window.isSecureContext) return "insecure";
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === "undefined") return "unsupported";
    return "idle";
  });
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);

  const start = useCallback(async () => {
    if (state === "recording" || state === "insecure" || state === "unsupported") return;
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      setState("denied");
      return;
    }
    const mimeType = MIME_CANDIDATES.find((m) => MediaRecorder.isTypeSupported(m));
    const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
    chunks.current = [];
    rec.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    rec.onstop = () => {
      stream.getTracks().forEach((t) => t.stop());
      const blob = new Blob(chunks.current, { type: rec.mimeType || "audio/webm" });
      setState("idle");
      // Ignore accidental taps (< 400 ms) instead of sending silence.
      if (Date.now() - startedAt.current >= 400 && blob.size > 0) onAudio(blob);
    };
    recRef.current = rec;
    startedAt.current = Date.now();
    rec.start();
    setState("recording");
  }, [state, onAudio]);

  const stop = useCallback(() => {
    if (recRef.current?.state === "recording") recRef.current.stop();
    recRef.current = null;
  }, []);

  return { state, start, stop };
}
