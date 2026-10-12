import { useCallback, useState } from "react";
import type { Api } from "../api";
import { useRecorder } from "../useRecorder";
import { getSpeechLang } from "../speechLang";
import { MicIcon } from "./Icons";

interface Props {
  api: Api;
  label: string;
  onText: (text: string) => void;
  onError: (e: unknown) => void;
  className?: string;
}

/** Tap, speak, tap again: PC1 only transcribes (no job), then the text goes to onText. */
export function VoiceAnswerButton({ api, label, onText, onError, className = "" }: Props) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const onAudio = useCallback(
    (blob: Blob) => {
      setBusy(true);
      setNote(null);
      api
        .transcribe(blob, getSpeechLang())
        .then(({ text }) => (text.trim() ? onText(text.trim()) : setNote("I didn't catch that, try again.")))
        .catch(onError)
        .finally(() => setBusy(false));
    },
    [api, onText, onError],
  );
  const mic = useRecorder(onAudio);
  const recording = mic.state === "recording";
  if (mic.state !== "idle" && !recording) return null; // no microphone here: typing stays available
  return (
    <>
      <button
        type="button"
        className={`voice-answer-btn ${recording ? "is-recording" : ""} ${className}`}
        onClick={mic.toggle}
        disabled={busy}
      >
        <MicIcon size={18} />
        <span>{busy ? "Listening back…" : recording ? "Listening… tap to send" : label}</span>
      </button>
      {note && <p className="voice-answer-note">{note}</p>}
    </>
  );
}
