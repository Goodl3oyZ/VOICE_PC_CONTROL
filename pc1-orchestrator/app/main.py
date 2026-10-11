"""Composition root: pick real or fake adapters from settings and build the app.

Run:  uvicorn app.main:build --factory --host 127.0.0.1 --port 8000   (behind Caddy for HTTPS)
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


def build(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    kb = Knowledge.load(s.knowledge_path)
    store = SqliteStore(s.db_path)
    bus = Broadcaster()

    if s.stt == "faster_whisper":
        from .adapters.faster_whisper_stt import FasterWhisperSTT
        prompt = " ".join(kb.display(a) for a in kb.apps)
        stt = FasterWhisperSTT(s.whisper_model, device=s.stt_device, compute_type=s.whisper_compute,
                               initial_prompt=prompt)
        stt.warm_up()  # load once at startup, not on the first command (§14.5 keep-warm)
    else:
        stt = FakeSTT("เปิดโน้ตแพด")

    if s.llm == "ollama":
        from .adapters.ollama_llm import OllamaLLM
        llm = OllamaLLM(s.ollama_url, s.ollama_model)
    elif s.llm == "openai":  # llama.cpp llama-server, vLLM, LM Studio
        from .adapters.openai_compat_llm import OpenAICompatLLM
        llm = OpenAICompatLLM(s.openai_url, s.openai_model, timeout=s.llm_timeout_s)
    else:
        llm = ScriptedLLM()  # refuses everything not handled by shortcuts

    heartbeat = None
    if s.pc2 == "http":
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
                                                  llm_timeout_s=s.llm_timeout_s,
                                                  stt_timeout_s=float(os.environ.get("VPC_STT_TIMEOUT_S", "20")),
                                                  heartbeat_enabled=heartbeat is not None))
    return create_app(orch, store, bus, static_dir=s.static_dir, heartbeat_interval=heartbeat)
