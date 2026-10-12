"""STT setups vs. command correctness: does the transcript run the same command as the reference text?

  # on PC1, clips = eval/golden/stt_phrases.txt spoken by several TTS voices as cNN_V.wav (+ noise added here)
  python eval/stt_bench.py <dir with phrases.txt and clips> [A B C D]

2026-10-12 (35 commands x 3 voices, clean + 12 dB noise): A today's setup (auto language) | B small, English
forced, vocabulary prompt 93 % / 91 %, 2.4 s | C small.en 89 % (repetition loops) | D medium.en (see CHECKLIST).
"""
import glob
import json
import os
import pathlib
import re
import sys
import time
import wave

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "contracts"), str(ROOT / "pc1-orchestrator")]
from faster_whisper import WhisperModel  # noqa: E402

from app.core.aliases import AliasNormalizer  # noqa: E402
from app.core.flows import flow_trigger  # noqa: E402
from app.core.knowledge import Knowledge  # noqa: E402
from app.core.shortcuts import match_shortcut  # noqa: E402

D = sys.argv[1]
kb = Knowledge.load(os.environ.get("VPC_KNOWLEDGE", ROOT / "pc1-orchestrator" / "data" / "knowledge.json"))
norm = AliasNormalizer(kb.aliases, [*kb.apps, *kb.sites])
phrases = [ln.strip() for ln in open(f"{D}/phrases.txt", encoding="utf-8") if ln.strip()]
APPS = " ".join(kb.display(a) for a in kb.apps)
RICH = ("Voice commands for a PC: open Chrome, YouTube, TikTok, Facebook, Instagram, X, Cursor, Word, Excel, "
        "PowerPoint, Steam, OBS, Notepad. Play lofi, skip ad, next song, pause the music, volume up 20 percent, "
        "mute, search for, open result two, close this tab, what tabs are open, start recording, start streaming, "
        "run the tests in demo, show the diff, revert the changes, wake up the PC, stop everything.")

def meaning(t):
    t = t.strip()
    sc = match_shortcut(norm(t), kb)
    if sc is not None:
        args = {k: re.sub(r"[^a-z0-9 ]", " ", str(v).lower()).split() for k, v in sc.arguments.items()}
        return ("tool", sc.tool, json.dumps(args, sort_keys=True))  # "lofi, hip-hop" == "lofi hip hop"
    fl = flow_trigger(t)
    if fl:
        return ("flow", fl)
    return ("text", re.sub(r"[^a-z0-9 ]", "", t.lower()).strip())

def load(f):
    with wave.open(f) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

rng = np.random.default_rng(7)
clips = sorted(glob.glob(f"{D}/c*.wav"))
data = []
for f in clips:
    idx = int(os.path.basename(f)[1:3])
    x = load(f)
    noisy = x + rng.normal(0, np.sqrt(np.mean(x ** 2) / 10 ** (12 / 10)), x.shape).astype(np.float32)  # 12 dB SNR
    data.append((phrases[idx], x, noisy))

SETUPS = [("A small, auto-language, app prompt (today)", "small", None, APPS),
          ("B small, English, rich prompt", "small", "en", RICH),
          ("C small.en, rich prompt", "small.en", "en", RICH),
          ("D medium.en, rich prompt", "medium.en", "en", RICH)]
only = sys.argv[2:] or None
for name, model, lang, prompt in SETUPS:
    if only and name[0] not in only:
        continue
    m = WhisperModel(model, device="cpu", compute_type="int8")
    ok = {"clean": 0, "noisy": 0}
    secs: list[float] = []
    misses: list[str] = []
    for ref, clean, noisy in data:
        for kind, audio in (("clean", clean), ("noisy", noisy)):
            t0 = time.time()
            segs, info = m.transcribe(audio, language=lang, vad_filter=True, beam_size=5, initial_prompt=prompt)
            text = "".join(s.text for s in segs).strip()
            secs.append(time.time() - t0)
            if meaning(text) == meaning(ref):
                ok[kind] += 1
            elif len(misses) < 8:
                misses.append(f"{kind}: {ref!r} -> {text!r}")
    n = len(data)
    s = sorted(secs)
    print(f"{name}: clean {ok['clean']}/{n} ({ok['clean']/n:.0%}), noisy {ok['noisy']}/{n} ({ok['noisy']/n:.0%}), "
          f"p50 {s[len(s)//2]:.2f}s p95 {s[int(len(s)*.95)]:.2f}s", flush=True)
    for x in misses:
        print("   ", x, flush=True)
    del m
