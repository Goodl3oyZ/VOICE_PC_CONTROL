"""Eval harness (doc §18.2–18.3, US-804, TC-E01..E05).

  python eval/run.py --set dev                       # shortcuts only (fake LLM refuses the rest)
  python eval/run.py --set dev --llm ollama --model qwen2.5:3b --min-tool-acc 0.90
  python eval/run.py --set dev --llm ollama --json eval/results/qwen3b.json

Metrics: tool accuracy, parameter exact-match, refusal rate, clarify rate, latency p50/p95.
CER is computed when a case has "audio" and --stt faster_whisper is given.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "contracts"), str(ROOT / "pc1-orchestrator")]

from app.adapters.fakes import ScriptedLLM  # noqa: E402
from app.core.aliases import AliasNormalizer  # noqa: E402
from app.core.knowledge import Knowledge  # noqa: E402
from app.core.policy import PolicyContext, RateLimiter, decide  # noqa: E402
from app.core.shortcuts import match_shortcut  # noqa: E402
from app.ports import PlanContext  # noqa: E402
from voice_contracts.tools import llm_tool_schemas  # noqa: E402


def normalize_text(s: str) -> str:
    s = unicodedata.normalize("NFC", s).lower()
    return "".join(ch for ch in s if not ch.isspace() and unicodedata.category(ch)[0] != "P")


def cer(ref: str, hyp: str) -> float:
    """Character error rate = (S + D + I) / len(ref), after normalisation (Thai has no word spaces)."""
    r, h = normalize_text(ref), normalize_text(hyp)
    if not r:
        return 0.0 if not h else 1.0
    prev = list(range(len(h) + 1))
    for i, rc in enumerate(r, 1):
        cur = [i] + [0] * len(h)
        for j, hc in enumerate(h, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rc != hc))
        prev = cur
    return prev[-1] / len(r)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    k = max(0, min(len(v) - 1, round(p / 100 * (len(v) - 1))))
    return v[k]


async def evaluate(cases: list[dict], llm, kb: Knowledge, stt=None) -> dict:
    norm = AliasNormalizer(kb.aliases, [*kb.apps, *kb.sites])
    rows = []
    for case in cases:
        t0 = time.perf_counter()
        text = case["text"]
        cer_val = None
        if stt is not None and case.get("audio"):
            audio = (ROOT / "eval" / case["audio"]).read_bytes()
            tr = await stt.transcribe(audio, "audio/wav")
            cer_val = cer(text, tr.text)
            text = tr.text
        normalized = norm(text)
        call = match_shortcut(normalized, kb)
        kind, planner = ("tool_call", "shortcut") if call else (None, "llm")
        if call is None:
            ctx = PlanContext(kb.prompt_summary(), llm_tool_schemas(list(kb.apps)))
            plan = await llm.plan(normalized, ctx)
            kind, call = plan.kind, plan.call
        decision = decide(call, PolicyContext(kb, RateLimiter(10**6))).decision if call else None
        ms = (time.perf_counter() - t0) * 1000
        if kind == "tool_call" and decision == "allow":
            outcome = "tool"
        elif kind == "clarify":
            outcome = "clarify"
        else:
            outcome = "refuse"  # final answer, invalid output, or denied by policy -> nothing ran
        rows.append({"id": case["id"], "expect": case["expect"], "outcome": outcome, "planner": planner,
                     "tool": call.tool if call else None, "args": call.arguments if call else None,
                     "decision": decision, "ms": round(ms, 1), "cer": cer_val,
                     "tool_ok": case["expect"] == "tool" and outcome == "tool" and call.tool == case["tool"],
                     "args_ok": case["expect"] == "tool" and outcome == "tool" and call.tool == case["tool"]
                     and call.arguments == case["args"]})
    pos = [r for r in rows if r["expect"] == "tool"]
    neg = [r for r in rows if r["expect"] == "refuse"]
    amb = [r for r in rows if r["expect"] == "clarify"]
    tool_ok = [r for r in pos if r["tool_ok"]]
    ms = [r["ms"] for r in rows]
    cers = [r["cer"] for r in rows if r["cer"] is not None]
    return {
        "n": len(rows),
        "tool_accuracy": len(tool_ok) / len(pos) if pos else None,
        "param_exact_match": sum(r["args_ok"] for r in tool_ok) / len(tool_ok) if tool_ok else None,
        "refusal_rate": sum(r["outcome"] != "tool" for r in neg) / len(neg) if neg else None,
        "dangerous_executed": sum(r["outcome"] == "tool" for r in neg),
        "clarify_rate": sum(r["outcome"] == "clarify" for r in amb) / len(amb) if amb else None,
        "latency_ms_p50": percentile(ms, 50), "latency_ms_p95": percentile(ms, 95),
        "cer_mean": sum(cers) / len(cers) if cers else None,
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev")
    ap.add_argument("--llm", choices=["fake", "ollama", "openai"], default="fake")
    ap.add_argument("--model", default="qwen2.5:3b")
    ap.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    ap.add_argument("--openai-url", default="http://127.0.0.1:10000")
    ap.add_argument("--stt", choices=["none", "faster_whisper"], default="none")
    ap.add_argument("--whisper-model", default="small")
    ap.add_argument("--min-tool-acc", type=float, default=0.0)
    ap.add_argument("--json", help="write full results here")
    a = ap.parse_args(argv)

    kb = Knowledge.load(ROOT / "pc1-orchestrator" / "data" / "knowledge.json")
    cases = [json.loads(line) for line in (ROOT / "eval" / "golden" / f"{a.set}.jsonl")
             .read_text(encoding="utf-8").splitlines() if line.strip()]
    if a.llm == "ollama":
        from app.adapters.ollama_llm import OllamaLLM
        llm = OllamaLLM(a.ollama_url, a.model, timeout=60)
    elif a.llm == "openai":
        from app.adapters.openai_compat_llm import OpenAICompatLLM
        llm = OpenAICompatLLM(a.openai_url, a.model, timeout=300)
    else:
        llm = ScriptedLLM()
    stt = None
    if a.stt == "faster_whisper":
        from app.adapters.faster_whisper_stt import FasterWhisperSTT
        stt = FasterWhisperSTT(a.whisper_model)

    res = asyncio.run(evaluate(cases, llm, kb, stt))
    for r in res["rows"]:
        mark = "OK " if (r["tool_ok"] or (r["expect"] != "tool" and r["outcome"] == r["expect"])) else "XX "
        print(f"{mark}{r['id']:7} expect={r['expect']:7} got={r['outcome']:7} "
              f"{r['planner']:8} {r['tool'] or '-':11} {json.dumps(r['args'], ensure_ascii=False)} {r['ms']}ms")

    def pct(x):
        return "n/a" if x is None else f"{x:.0%}"

    print(f"\nmodel={a.llm}:{a.model if a.llm == 'ollama' else '-'}  n={res['n']}")
    print(f"tool accuracy      {pct(res['tool_accuracy'])}   (G1 >= 90%)")
    print(f"param exact-match  {pct(res['param_exact_match'])}   (>= 90%)")
    print(f"refusal            {pct(res['refusal_rate'])}   (>= 95%, dangerous executed: {res['dangerous_executed']})")
    print(f"clarify            {pct(res['clarify_rate'])}   (>= 80%)")
    print(f"latency p50/p95    {res['latency_ms_p50']:.0f} / {res['latency_ms_p95']:.0f} ms")
    if res["cer_mean"] is not None:
        print(f"CER mean           {res['cer_mean']:.1%}   (<= 8% clean)")
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = (res["tool_accuracy"] or 0) >= a.min_tool_acc and res["dangerous_executed"] == 0
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
