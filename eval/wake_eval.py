"""Wake-word eval (Gate G4 false triggers): real Whisper + wake_filter on recorded/synthesized clips.

  python eval/wake_eval.py --clips /tmp/wake_wav [--model small]
Each clip <id>.wav is matched to eval/golden/wake_en.jsonl. Reports false accepts (room speech that would
have become a command) and missed commands.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "contracts"), str(ROOT / "pc1-orchestrator")]

from app.core.wake import wake_filter  # noqa: E402


async def main_async(a: argparse.Namespace) -> int:
    from app.adapters.faster_whisper_stt import FasterWhisperSTT
    stt = FasterWhisperSTT(a.model, device="cpu", language=None)  # as in production English mode
    cases = [json.loads(x) for x in (ROOT / "eval" / "golden" / "wake_en.jsonl").read_text(encoding="utf-8")
             .splitlines() if x.strip()]
    false_accept = missed = 0
    times = []
    for c in cases:
        audio = (Path(a.clips) / f"{c['id']}.wav").read_bytes()
        t0 = time.monotonic()
        tr = await stt.transcribe(audio, "audio/wav")
        times.append(time.monotonic() - t0)
        got = wake_filter(tr.text).kind
        bad = (c["expect"] == "ignore" and got != "ignore") or (c["expect"] != "ignore" and got != c["expect"])
        false_accept += c["expect"] == "ignore" and got != "ignore"
        missed += c["expect"] != "ignore" and got != c["expect"]
        print(f"{'XX' if bad else 'OK'} {c['id']} expect={c['expect']:9} got={got:9} heard={tr.text!r}")
    n_ignore = sum(c["expect"] == "ignore" for c in cases)
    n_wake = len(cases) - n_ignore
    print("SUMMARY " + json.dumps({"room_speech": n_ignore, "false_accepts": false_accept,
                                   "wake_commands": n_wake, "missed": missed,
                                   "stt_p50_s": round(sorted(times)[len(times) // 2], 2)}))
    return 0 if false_accept == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clips", required=True)
    ap.add_argument("--model", default="small")
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
