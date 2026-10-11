from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field

from app.adapters.fakes import FakePC2, FakeSTT, ListNotifier, ScriptedLLM
from app.adapters.sqlite_store import SqliteStore
from app.core.knowledge import Knowledge
from app.core.orchestrator import Orchestrator, OrchestratorConfig
from voice_contracts import tools as tools_mod

ROOT = Path(__file__).resolve().parent.parent
SECRET = b"test-secret-0123456789-abcdefghijklmnop"


@pytest.fixture
def kb() -> Knowledge:
    return Knowledge.load(ROOT / "pc1-orchestrator" / "data" / "knowledge.json")


@pytest.fixture
def store() -> SqliteStore:
    return SqliteStore(":memory:")


class Rig:
    """Orchestrator wired to fakes, with handles to every fake for assertions."""

    def __init__(self, kb: Knowledge, store: SqliteStore, **cfg: object):
        self.stt = FakeSTT("เปิดโน้ตแพด")
        self.llm = ScriptedLLM()
        self.pc2 = FakePC2()
        self.notify = ListNotifier()
        self.store = store
        self.orch = Orchestrator(stt=self.stt, llm=self.llm, tools=self.pc2, store=store,
                                 notify=self.notify, knowledge=kb, config=OrchestratorConfig(**cfg))

    async def run_text(self, text: str, device: str = "phone"):
        job = await self.orch.submit_text(text, device)
        await self.orch.wait_idle()
        return self.orch.get_job(job.id)


@pytest.fixture
def rig_factory(kb, store):
    return lambda **cfg: Rig(kb, store, **cfg)


@pytest.fixture
def rig(rig_factory) -> Rig:
    return rig_factory()


class SendMessageArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: str = Field(max_length=50)
    text: str = Field(max_length=500)


@pytest.fixture
def risky_tool(monkeypatch):
    """Registers a risk-3 tool (Phase 2 style) to exercise the confirm path."""
    spec = tools_mod.ToolSpec("send_message", 3, SendMessageArgs, "send a message", 2)
    monkeypatch.setitem(tools_mod.TOOLS, "send_message", spec)
    return spec


@pytest.fixture
def api(rig):
    """HTTP client for the API with a bearer device token (CLI/test mode)."""
    from fastapi.testclient import TestClient

    from app.adapters.notify import Broadcaster
    from app.api.app import create_app
    bus = Broadcaster()
    rig.orch.notify = bus
    app = create_app(rig.orch, rig.store, bus)
    token = rig.store.create_device("phone")
    with TestClient(app) as client:
        client.headers["Authorization"] = f"Bearer {token}"
        yield client, rig, token
