"""The example configs and deployment files shipped in the repo must stay valid and secret-free."""
from __future__ import annotations

import re
from pathlib import Path

from agent.config import AgentConfig
from app.core.knowledge import Knowledge

ROOT = Path(__file__).resolve().parent.parent


def test_example_agent_config_parses_and_uses_outbound_mode():
    cfg = AgentConfig.load(ROOT / "pc2-agent" / "agent_config.json")
    assert cfg.pc1_ws_url and cfg.pc1_ws_url.startswith("wss://")
    assert cfg.apps


def test_example_knowledge_parses_and_matches_agent_apps():
    kb = Knowledge.load(ROOT / "pc1-orchestrator" / "data" / "knowledge.json")
    agent = AgentConfig.load(ROOT / "pc2-agent" / "agent_config.json")
    assert set(agent.apps) <= set(kb.apps)


def test_env_examples_have_only_placeholders():
    for p in [ROOT / ".env.example", ROOT / "infra" / "pc1" / "voice-pc-control.env.example"]:
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"GOCSPX-[A-Za-z0-9_-]{10,}", text), p
        assert not re.search(r"=[0-9a-f]{64}\s*$", text, re.M), p  # no real 64-hex secrets


def test_deploy_files_exist():
    for rel in ["infra/pc1/deploy.sh", "infra/pc1/voice-pc-control.service", "infra/pc1/vpc-cli",
                "infra/cloudflared/ingress-example.yml", "docker-compose.yml", "docs/DEPLOYMENT.md"]:
        assert (ROOT / rel).is_file(), rel
