"""Composition root: pick real or fake adapters from settings and build the app.

Run:  uvicorn app.main:build --factory --host 127.0.0.1 --port 8000   (published by a Cloudflare tunnel)
"""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from .adapters.fakes import FakePC2, FakeSTT, ScriptedLLM
from .adapters.notify import Broadcaster
from .adapters.sqlite_store import SqliteStore
from .api.app import create_app
from .core.knowledge import Knowledge
from .core.orchestrator import Orchestrator, OrchestratorConfig
from .settings import Settings

STT_WORDS = ("Play lofi, skip ad, next song, pause the music, volume up 20 percent, mute, search for, open result "
             "two, close this tab, what tabs are open, start recording, stop recording, start streaming, show the "
             "diff, run the tests, revert the changes, wake up the PC, stop everything, what's on the screen.")


def stt_prompt(kb: Knowledge) -> str:
    """Whisper prompt: the owner's apps, sites and projects plus the command words (keeps names spelled right)."""
    names = ["YouTube", "TikTok", "Facebook", "Instagram", "X", "Cursor", "Word", "Excel", "PowerPoint", "Steam",
             "OBS", "Google", "GitHub", "Gmail"]  # brand spellings first: they win over "Youtube"
    names += [kb.display(a, "en") for a in kb.apps] + [s.title() for s in kb.sites] + list(kb.projects)
    seen: list[str] = []
    for n in names:
        if n and n.lower() not in {x.lower() for x in seen}:
            seen.append(n)
    return "Voice commands for a PC: open " + ", ".join(seen)[:500] + ". " + STT_WORDS


def build(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    kb = Knowledge.load(s.knowledge_path)
    store = SqliteStore(s.db_path)
    bus = Broadcaster()

    if s.stt == "faster_whisper":
        from .adapters.faster_whisper_stt import FasterWhisperSTT
        # English mode: the language is FIXED to English. Auto-detect heard accented English as another language
        # and mangled the words (owner feedback 2026-10-12; benchmark in eval/stt_bench.py). The prompt biases
        # Whisper toward the words commands actually use.
        stt = FasterWhisperSTT(s.whisper_model, device=s.stt_device, compute_type=s.whisper_compute,
                               language="en" if s.language == "en" else "th",
                               initial_prompt=stt_prompt(kb) if s.language == "en" else
                               " ".join(kb.display(a) for a in kb.apps))
        stt.warm_up()  # load once at startup, not on the first command (§14.5 keep-warm)
    else:
        stt = FakeSTT("เปิดโน้ตแพด")

    if s.llm == "ollama":
        from .adapters.ollama_llm import OllamaLLM
        llm = OllamaLLM(s.ollama_url, s.ollama_model, timeout=s.llm_timeout_s, language=s.language)
    elif s.llm == "openai":  # llama.cpp llama-server, vLLM, LM Studio
        from .adapters.openai_compat_llm import OpenAICompatLLM
        llm = OpenAICompatLLM(s.openai_url, s.openai_model, timeout=s.llm_timeout_s, language=s.language)
    else:
        llm = ScriptedLLM()  # refuses everything not handled by shortcuts

    heartbeat, hub = None, None
    if s.pc2 == "relay":  # PC2 dials out to /agent/ws (no VPN, no open port on the notebook)
        if len(s.pc2_secret) < 32:
            raise SystemExit("VPC_PC2_SECRET must be set (>= 32 chars) when VPC_PC2=relay")
        from .adapters.agent_hub import AgentHub, PC2RelayTools
        hub = AgentHub(s.pc2_secret.encode())
        tools = PC2RelayTools(hub, s.pc2_secret.encode(), timeout=160)  # >= slowest tool (run_tests)
        heartbeat = s.heartbeat_s
    elif s.pc2 == "http":
        if len(s.pc2_secret) < 32:
            raise SystemExit("VPC_PC2_SECRET must be set (>= 32 chars) when VPC_PC2=http")
        from .adapters.pc2_http import PC2HttpTools
        tools = PC2HttpTools(s.pc2_url, s.pc2_secret.encode(), verify=s.pc2_ca or True)
        heartbeat = s.heartbeat_s
    else:
        tools = FakePC2()

    orch = Orchestrator(stt=stt, llm=llm, tools=tools, store=store, notify=bus, knowledge=kb,
                        config=OrchestratorConfig(confirm_timeout_s=s.confirm_timeout_s,
                                                  stt_confidence_min=s.stt_confidence_min,
                                                  llm_timeout_s=s.llm_timeout_s, language=s.language,
                                                  tool_timeout_s=s.tool_timeout_s,
                                                  stt_timeout_s=float(os.environ.get("VPC_STT_TIMEOUT_S", "20")),
                                                  heartbeat_enabled=heartbeat is not None,
                                                  pc2_mac=os.environ.get("VPC_PC2_MAC", ""),
                                                  wol_broadcast=os.environ.get("VPC_WOL_BROADCAST",
                                                                               "255.255.255.255")))
    webauth = None
    if s.public_url:
        if len(s.session_secret) < 32:
            raise SystemExit("VPC_SESSION_SECRET must be set (>= 32 chars) when VPC_PUBLIC_URL is set")
        from .api.webauth import WebAuth, WebAuthConfig
        webauth = WebAuth(WebAuthConfig(
            public_url=s.public_url, session_secret=s.session_secret.encode(),
            google_client_id=s.google_client_id, google_client_secret=s.google_client_secret,
            allowed_emails={e.strip().lower() for e in s.allowed_emails.split(",") if e.strip()}), store)
    return create_app(orch, store, bus, static_dir=s.static_dir, heartbeat_interval=heartbeat,
                      webauth=webauth, hub=hub, allow_bearer=s.allow_bearer)
