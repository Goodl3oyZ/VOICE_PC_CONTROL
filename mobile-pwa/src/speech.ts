import type { Job } from "./api";
import { spokenText } from "./vad";

/** Spoken replies (Phase 4) with the phone's built-in English text-to-speech; nothing is sent anywhere. */
export function speak(text: string): void {
  const synth = window.speechSynthesis;
  if (!synth || !text) return;
  synth.cancel(); // newest result wins
  const u = new SpeechSynthesisUtterance(spokenText(text));
  u.lang = "en-US";
  u.rate = 1.05;
  const voice = synth.getVoices().find((v) => v.lang.startsWith("en"));
  if (voice) u.voice = voice;
  synth.speak(u);
}

export function isSpeaking(): boolean {
  return !!window.speechSynthesis?.speaking;
}

/** What to say for a job update, or null if this state isn't worth speaking. */
export function utteranceFor(job: Job): string | null {
  switch (job.state) {
    case "done":
      return job.summary || "Done";
    case "failed":
      return job.error || job.summary || "That didn't work";
    case "cancelled":
      return "Stopped";
    case "clarifying":
      return job.question;
    case "awaiting_confirm":
      return "Please confirm on the phone";
    default:
      return null;
  }
}
