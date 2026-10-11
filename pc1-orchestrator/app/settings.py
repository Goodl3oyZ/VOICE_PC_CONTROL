"""12-factor configuration from environment variables (§19.5). Secrets never live in git."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Settings:
    db_path: str = field(default_factory=lambda: _env("VPC_DB", str(BASE / "data" / "vpc.sqlite3")))
    knowledge_path: str = field(default_factory=lambda: _env("VPC_KNOWLEDGE",
                                                             str(BASE / "data" / "knowledge.json")))
    stt: str = field(default_factory=lambda: _env("VPC_STT", "fake"))  # fake | faster_whisper
    whisper_model: str = field(default_factory=lambda: _env("VPC_WHISPER_MODEL", "small"))
    whisper_compute: str = field(default_factory=lambda: _env("VPC_WHISPER_COMPUTE", "int8"))
    llm: str = field(default_factory=lambda: _env("VPC_LLM", "fake"))  # fake | ollama
    ollama_url: str = field(default_factory=lambda: _env("VPC_OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(default_factory=lambda: _env("VPC_OLLAMA_MODEL", "qwen2.5:3b"))
    openai_url: str = field(default_factory=lambda: _env("VPC_OPENAI_URL", "http://127.0.0.1:10000"))
    openai_model: str = field(default_factory=lambda: _env("VPC_OPENAI_MODEL", ""))
    llm_timeout_s: float = field(default_factory=lambda: float(_env("VPC_LLM_TIMEOUT_S", "30")))
    stt_device: str = field(default_factory=lambda: _env("VPC_STT_DEVICE", "cpu"))
    # --- public web access (Cloudflare tunnel): Google login + paired-device cookie ---
    public_url: str = field(default_factory=lambda: _env("VPC_PUBLIC_URL"))  # e.g. https://pc.example.com
    session_secret: str = field(default_factory=lambda: _env("VPC_SESSION_SECRET"))
    google_client_id: str = field(default_factory=lambda: _env("VPC_GOOGLE_CLIENT_ID"))
    google_client_secret: str = field(default_factory=lambda: _env("VPC_GOOGLE_CLIENT_SECRET"))
    allowed_emails: str = field(default_factory=lambda: _env("VPC_ALLOWED_EMAILS"))  # comma separated
    allow_bearer: bool = field(default_factory=lambda: _env("VPC_ALLOW_BEARER", "true").lower() == "true")
    pc2: str = field(default_factory=lambda: _env("VPC_PC2", "fake"))  # fake | http | relay
    pc2_url: str = field(default_factory=lambda: _env("VPC_PC2_URL", "https://pc2:8765"))
    pc2_secret: str = field(default_factory=lambda: _env("VPC_PC2_SECRET"))
    pc2_ca: str = field(default_factory=lambda: _env("VPC_PC2_CA"))  # CA bundle path for PC2 TLS
    static_dir: str = field(default_factory=lambda: _env("VPC_STATIC_DIR",
                                                         str(BASE.parent / "mobile-pwa" / "dist")))
    heartbeat_s: float = field(default_factory=lambda: float(_env("VPC_HEARTBEAT_S", "5")))
    confirm_timeout_s: float = field(default_factory=lambda: float(_env("VPC_CONFIRM_TIMEOUT_S", "120")))
    stt_confidence_min: float = field(default_factory=lambda: float(_env("VPC_STT_CONF_MIN", "0.7")))
