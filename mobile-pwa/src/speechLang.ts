import { useCallback, useEffect, useState } from "react";

/** Which language PC1 listens for: forcing English turned Thai song names into nonsense ("Errandon, mind"). */
export type SpeechLang = "en" | "th";

const KEY = "vpc.speech_lang";
const EVENT = "vpc-speech-lang";

export function getSpeechLang(): SpeechLang {
  try {
    return localStorage.getItem(KEY) === "th" ? "th" : "en";
  } catch {
    return "en";
  }
}

/** Shared by the main mic and every voice-answer button, so one switch changes them all. */
export function useSpeechLang(): [SpeechLang, (l: SpeechLang) => void] {
  const [lang, setLang] = useState<SpeechLang>(getSpeechLang);
  useEffect(() => {
    const on = () => setLang(getSpeechLang());
    window.addEventListener(EVENT, on);
    return () => window.removeEventListener(EVENT, on);
  }, []);
  const set = useCallback((l: SpeechLang) => {
    try {
      localStorage.setItem(KEY, l);
    } catch {
      /* per-device preference only */
    }
    setLang(l);
    window.dispatchEvent(new Event(EVENT));
  }, []);
  return [lang, set];
}
