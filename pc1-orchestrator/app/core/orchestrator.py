"""Use cases: HandleCommand, Reply (clarify), Confirm, Stop, Heartbeat (doc §14, §15.4).

Pipeline per job (§14.1): [transcribe] -> normalise -> plan (shortcut | LLM) -> route (policy)
-> [confirm on phone] -> dispatch to PC2 -> verify -> summarise -> done.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from voice_contracts.tools import TOOLS, llm_tool_schemas

from ..ports import (
    AuditWriteError,
    LLMPort,
    NotifyPort,
    PC2Unavailable,
    PlanContext,
    PlanResult,
    StorePort,
    STTPort,
    ToolPort,
)
from .aliases import AliasNormalizer
from .capabilities import help_summary, is_help
from .i18n import YES_WORDS, Messages, is_english
from .jobs import Job, JobState, new_job_id
from .knowledge import Knowledge
from .policy import PolicyContext, RateLimiter, decide
from .shortcuts import match_shortcut
from .summary import deny_message, summarize

log = logging.getLogger("pc1.orchestrator")
S = JobState


class Conflict(Exception):
    """Request doesn't fit the job's current state (maps to HTTP 409)."""


class NotFound(Exception):
    pass


@dataclass
class OrchestratorConfig:
    stt_confidence_min: float = 0.7
    confirm_timeout_s: float = 120.0
    clarify_timeout_s: float = 300.0  # unanswered questions expire instead of blocking the UI forever
    stt_timeout_s: float = 10.0
    llm_timeout_s: float = 30.0
    tool_timeout_s: float = 15.0
    job_timeout_s: float = 120.0
    max_steps: int = 8
    multi_step: bool = False  # Phase 1: one tool per command; ReAct loop comes in Phase 3
    heartbeat_enabled: bool = False
    pc2_offline_after_s: float = 15.0
    breaker_threshold: int = 3
    breaker_cooldown_s: float = 30.0
    rate_limit_per_min: int = 20
    language: str = "th"  # "en" = English-only commands, English replies


class Orchestrator:
    def __init__(self, *, stt: STTPort, llm: LLMPort, tools: ToolPort, store: StorePort,
                 notify: NotifyPort, knowledge: Knowledge, config: OrchestratorConfig | None = None,
                 clock: Callable[[], float] = time.time):
        self.stt, self.llm, self.tools, self.store, self.notify = stt, llm, tools, store, notify
        self.kb = knowledge
        self.cfg = config or OrchestratorConfig()
        self.clock = clock
        self.t = Messages(self.cfg.language)
        self.normalize = AliasNormalizer(knowledge.aliases, [*knowledge.apps, *knowledge.sites])
        self.rate = RateLimiter(self.cfg.rate_limit_per_min, 60.0, clock)
        self._active: dict[str, Job] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._pc2_lock = asyncio.Lock()
        self.pc2_last_seen: float | None = None
        self.pc2_status: dict[str, Any] = {}
        self._pc2_was_online: bool | None = None
        self._failures = 0
        self._breaker_until = 0.0

    # ------------------------------------------------------------------ public use cases
    async def submit_text(self, text: str, device: str) -> Job:
        text = text.strip()
        if not text:
            raise ValueError("empty command")
        job = Job(id=new_job_id(self.clock()), device=device, source="text", text=text[:1000],
                  created_at=self.clock(), updated_at=self.clock())
        return await self._start(job)

    async def submit_audio(self, audio: bytes, mime: str, device: str) -> Job:
        job = Job(id=new_job_id(self.clock()), device=device, source="audio",
                  created_at=self.clock(), updated_at=self.clock())
        return await self._start(job, audio, mime)

    async def reply(self, job_id: str, text: str, device: str) -> Job:
        job = self._get_active(job_id)
        if job.state != S.CLARIFYING:
            raise Conflict("job is not waiting for an answer")
        if text.strip().lower() not in YES_WORDS and text.strip() and not self._language_ok(text):
            raise ValueError(self.t("only_english"))
        text = text.strip()[:1000]
        if not text:
            raise ValueError("empty reply")
        if job.clarify_kind == "stt_confirm":
            if text.lower() not in YES_WORDS:
                job.text = text  # user corrected the transcript
            job.normalized = self.normalize(job.text)
        else:
            job.history.append({"q": job.question or "", "a": text})
            job.normalized = self.normalize(f"{job.text} {text}")
        job.question, job.clarify_kind = None, None
        self._audit("reply", job, {"device": device})
        self._spawn(job, self._resume_planning(job))
        return job

    async def confirm(self, job_id: str, approve: bool, args_hash: str, device: str) -> Job:
        job = self._get_active(job_id)
        if job.state != S.AWAITING_CONFIRM or not job.pending:
            raise Conflict("job is not awaiting confirmation")
        pending = job.pending
        if self.clock() > pending["expires_at"]:
            await self._cancel(job, self.t("confirm_expired"))
            raise Conflict("confirmation expired")
        self._audit("confirm", job, {"device": device, "approve": approve, "args_hash": args_hash})
        if not approve:
            await self._cancel(job, self.t("not_approved"))
            return job
        if args_hash != pending["args_hash"]:
            await self._fail(job, self.t("args_mismatch"), "denied")
            return job
        self._spawn(job, self._run_confirmed(job))
        return job

    async def cancel(self, job_id: str, device: str) -> Job:
        """Cancel one job (e.g. an unanswered question). Works for stale jobs left in the DB too."""
        job = self._active.get(job_id)
        if job is None:
            d = self.store.get_job(job_id)
            if d is None:
                raise NotFound(job_id)
            job = Job.from_dict(d)
            if job.terminal:
                raise Conflict("job already finished")
            self._active[job.id] = job
        await self._cancel(job, self.t("user_cancelled"))
        task = self._tasks.pop(job.id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        self._audit("cancel", job, {"device": device}, best_effort=True)
        return job

    async def recover(self) -> int:
        """At startup: jobs left mid-flight by a restart can never finish — close them as cancelled."""
        n = 0
        for d in self.store.list_unfinished_jobs():
            if d["id"] in self._active:
                continue
            job = Job.from_dict(d)
            self._active[job.id] = job
            await self._cancel(job, self.t("stale_job"))
            n += 1
        if n:
            log.info("recovered %d unfinished job(s) as cancelled", n)
        return n

    async def stop(self, device: str) -> dict[str, Any]:
        await self.recover()  # stale DB jobs (e.g. after a restart) are cleared by Stop too
        cancelled = []
        for job in list(self._active.values()):
            if not job.terminal:
                await self._cancel(job, self.t("user_stopped"))
                cancelled.append(job.id)
            task = self._tasks.pop(job.id, None)
            if task and task is not asyncio.current_task():
                task.cancel()
        pc2_ok = False
        try:
            res = await asyncio.wait_for(self.tools.stop_all(), 2.0)
            pc2_ok = res.ok
        except (PC2Unavailable, TimeoutError) as e:
            log.warning("stop_all on PC2 failed: %s", e)
        self._audit("stop", None, {"device": device, "cancelled": cancelled, "pc2_ok": pc2_ok},
                    best_effort=True)
        return {"cancelled": cancelled, "pc2_stopped": pc2_ok}

    async def heartbeat(self) -> bool:
        try:
            res = await asyncio.wait_for(self.tools.status(), 3.0)
            if res.ok:
                self.pc2_last_seen = self.clock()
                self.pc2_status = res.data
        except (PC2Unavailable, TimeoutError):
            pass
        online = self.pc2_online
        if online != self._pc2_was_online:
            self._pc2_was_online = online
            await self.notify.publish({"type": "pc2.status", "online": online, "status": self.pc2_status})
        return online

    @property
    def pc2_online(self) -> bool:
        return (self.pc2_last_seen is not None
                and self.clock() - self.pc2_last_seen <= self.cfg.pc2_offline_after_s)

    def get_job(self, job_id: str) -> Job:
        if job_id in self._active:
            return self._active[job_id]
        d = self.store.get_job(job_id)
        if d is None:
            raise NotFound(job_id)
        return Job.from_dict(d)

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_jobs(limit)

    async def wait_idle(self) -> None:
        """Test helper: wait until no background pipeline task is running."""
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)

    # ------------------------------------------------------------------ pipeline
    async def _start(self, job: Job, audio: bytes | None = None, mime: str = "") -> Job:
        self._active[job.id] = job
        self._audit("created", job, {"device": job.device, "source": job.source})
        await self._save(job)
        self._spawn(job, self._pipeline(job, audio, mime))
        return job

    def _spawn(self, job: Job, coro: Any) -> None:
        task = asyncio.create_task(self._guard(job, coro))
        self._tasks[job.id] = task

    async def _guard(self, job: Job, coro: Any) -> None:
        try:
            await asyncio.wait_for(coro, self.cfg.job_timeout_s)
        except asyncio.CancelledError:
            if not job.terminal:
                await self._cancel(job, self.t("cancelled"))
            raise
        except TimeoutError:
            await self._fail(job, self.t("job_timeout"))
        except AuditWriteError:
            await self._fail(job, self.t("audit_failed"))
        except Exception as e:  # noqa: BLE001 — never leave a job floating
            log.exception("pipeline error in %s", job.id)
            await self._fail(job, self.t("internal_error", name=type(e).__name__))
        finally:
            if self._tasks.get(job.id) is asyncio.current_task():
                self._tasks.pop(job.id, None)

    async def _pipeline(self, job: Job, audio: bytes | None, mime: str) -> None:
        if job.source == "audio":
            await self._move(job, S.TRANSCRIBING)
            t0 = self.clock()
            try:
                tr = await asyncio.wait_for(self.stt.transcribe(audio or b"", mime),
                                            self.cfg.stt_timeout_s)
            except TimeoutError:
                self._event(job, "stt", "fail", t0)
                await self._fail(job, self.t("stt_timeout"))
                return
            self._event(job, "stt", "ok", t0)
            job.text, job.stt_confidence = tr.text.strip(), tr.confidence
            if not job.text:
                await self._fail(job, self.t("no_speech"))
                return
            if not self._language_ok(job.text):
                await self._fail(job, self.t("only_english"), "rejected_language")
                return
            job.normalized = self.normalize(job.text)
            is_stop = (sc := match_shortcut(job.normalized, self.kb)) is not None and sc.tool == "stop_all"
            if tr.confidence < self.cfg.stt_confidence_min and not is_stop:  # Stop must never wait
                job.question = self.t("stt_confirm", text=job.text)
                job.clarify_kind = "stt_confirm"
                await self._ask(job)
                return
        else:
            if not self._language_ok(job.text):
                await self._fail(job, self.t("only_english"), "rejected_language")
                return
            job.normalized = self.normalize(job.text)
        if is_help(job.normalized):  # answered by PC1 itself; nothing is sent to PC2
            await self._move(job, S.PLANNING)
            job.planner, job.summary = "help", help_summary(self.kb, self.cfg.language)
            await self._done(job)
            return
        await self._plan_loop(job)

    def _language_ok(self, text: str) -> bool:
        """English-only mode: reject other languages instead of guessing (Whisper is weak in Thai here)."""
        return self.cfg.language != "en" or is_english(text)

    async def _resume_planning(self, job: Job) -> None:
        await self._plan_loop(job)

    async def _plan_loop(self, job: Job) -> None:
        while len(job.steps) < self.cfg.max_steps:
            await self._move(job, S.PLANNING)
            plan = await self._plan(job)
            if job.terminal:
                return
            if plan.kind == "clarify":
                job.question, job.clarify_kind = plan.message or self.t("clarify_default"), "llm"
                await self._ask(job)
                return
            if plan.kind == "final":
                if job.steps:
                    await self._done(job)
                else:
                    await self._fail(job, plan.message or self.t("no_tool"), "refused")
                return
            if plan.kind == "invalid" or plan.call is None:
                await self._fail(job, self.t("llm_invalid"))
                return
            call = plan.call
            if job.steps and job.steps[-1]["tool"] == call.tool \
                    and job.steps[-1]["arguments"] == call.arguments:
                await self._fail(job, self.t("loop_repeat"))
                return

            await self._move(job, S.ROUTING)
            t0 = self.clock()
            ctx = PolicyContext(self.kb, self.rate, bool(self.pc2_status.get("kill_switch")),
                                job.tainted)
            decision = decide(call, ctx)
            self._event(job, "route", decision.decision, t0, tool=call.tool, risk=decision.risk)
            self._audit("route", job, {"tool": call.tool, "arguments": call.arguments,
                                       "decision": decision.decision, "reason": decision.reason,
                                       "risk": decision.risk, "args_hash": decision.args_hash})
            if decision.decision == "deny":
                await self._fail(job, deny_message(decision.reason, self.cfg.language), "denied")
                return
            if decision.decision == "confirm":
                job.pending = {"tool": call.tool, "arguments": decision.arguments,
                               "args_hash": decision.args_hash, "risk": decision.risk,
                               "reason": decision.reason,
                               "expires_at": self.clock() + self.cfg.confirm_timeout_s}
                await self._move(job, S.AWAITING_CONFIRM)
                asyncio.create_task(self._expire_confirm(job, decision.args_hash))
                return
            ok = await self._execute(job, call.tool, decision.arguments, decision.args_hash or "",
                                     approved=False)
            if not ok:
                return
            if job.planner == "shortcut" or not self.cfg.multi_step:
                await self._done(job)
                return
        await self._fail(job, self.t("max_steps"))

    async def _plan(self, job: Job) -> PlanResult:
        if not job.steps:
            shortcut = match_shortcut(job.normalized, self.kb)
            if shortcut is not None:
                job.planner = "shortcut"
                return PlanResult(kind="tool_call", call=shortcut)
        job.planner = "llm"
        ctx = PlanContext(
            knowledge_summary=self.kb.prompt_summary(),
            tools=llm_tool_schemas(list(self.kb.apps)),
            history=job.history,
            observations=[{"tool": s["tool"], "arguments": s["arguments"], "result": s["result"],
                           "trusted": not s["result"].get("untrusted", False)} for s in job.steps],
        )
        t0 = self.clock()
        for attempt in range(2):  # invalid JSON -> retry once (§14.2 step 4)
            try:
                plan = await asyncio.wait_for(self.llm.plan(job.normalized, ctx), self.cfg.llm_timeout_s)
            except TimeoutError:
                self._event(job, "plan", "fail", t0)
                return PlanResult(kind="invalid", message="LLM timeout")
            if plan.kind != "invalid":
                self._event(job, "plan", "ok", t0)
                return plan
            log.info("invalid plan for %s (attempt %d): %s", job.id, attempt + 1, plan.message)
        self._event(job, "plan", "fail", t0)
        return plan

    async def _run_confirmed(self, job: Job) -> None:
        p = job.pending or {}
        ok = await self._execute(job, p["tool"], p["arguments"], p["args_hash"], approved=True)
        if ok:
            await self._done(job)

    async def _execute(self, job: Job, tool: str, args: dict[str, Any], args_hash: str,
                       approved: bool) -> bool:
        now = self.clock()
        if now < self._breaker_until:
            await self._fail(job, self.t("breaker"))
            return False
        if self.cfg.heartbeat_enabled and not self.pc2_online:
            await self._fail(job, self.t("pc2_offline"))
            return False
        step = len(job.steps)
        async with self._pc2_lock:  # one job at a time per PC2 (§14.7)
            if job.terminal:
                return False
            await self._move(job, S.DISPATCHING)  # audited: fails closed before touching PC2
            await self._move(job, S.RUNNING)
            t0 = self.clock()
            try:
                result = await asyncio.wait_for(
                    self.tools.call(tool, args, f"{job.id}:s{step}",
                                    approved_hash=args_hash if approved else None),
                    self.cfg.tool_timeout_s)
            except PC2Unavailable as e:
                self._event(job, "tool", "fail", t0, tool=tool)
                self._failures += 1
                if self._failures >= self.cfg.breaker_threshold:
                    self._breaker_until = self.clock() + self.cfg.breaker_cooldown_s
                await self._fail(job, self.t("pc2_unreachable", reason=e))
                return False
            except TimeoutError:
                self._event(job, "tool", "fail", t0, tool=tool)
                await self._fail(job, self.t("pc2_slow"))
                return False
            self._failures = 0
            self.pc2_last_seen = self.clock()
            self._event(job, "tool", "ok" if result.ok else "fail", t0, tool=tool,
                        risk=TOOLS[tool].risk)
        if job.terminal:  # stopped while PC2 was working
            return False
        await self._move(job, S.VERIFYING)
        job.steps.append({"tool": tool, "arguments": args, "result": result.model_dump()})
        if result.untrusted:
            job.tainted = True
        self._audit("tool_result", job, {"tool": tool, "ok": result.ok, "verified": result.verified,
                                         "error": result.error})
        job.summary = summarize(tool, args, result, self.kb, self.cfg.language)
        if not (result.ok and result.verified):
            await self._fail(job, job.summary)
            return False
        return True

    async def _ask(self, job: Job) -> None:
        await self._move(job, S.CLARIFYING)
        asyncio.create_task(self._expire_clarify(job, job.question))

    async def _expire_clarify(self, job: Job, question: str | None) -> None:
        await asyncio.sleep(self.cfg.clarify_timeout_s)
        if job.state == S.CLARIFYING and job.question == question:
            await self._cancel(job, self.t("clarify_expired"))

    async def _expire_confirm(self, job: Job, args_hash: str | None) -> None:
        await asyncio.sleep(self.cfg.confirm_timeout_s)
        if job.state == S.AWAITING_CONFIRM and job.pending and job.pending["args_hash"] == args_hash:
            await self._cancel(job, self.t("confirm_expired"))

    # ------------------------------------------------------------------ state helpers
    def _get_active(self, job_id: str) -> Job:
        job = self._active.get(job_id)
        if job is None:
            if self.store.get_job(job_id) is None:
                raise NotFound(job_id)
            raise Conflict("job already finished")
        return job

    async def _move(self, job: Job, state: JobState) -> None:
        old = job.transition(state, self.clock())
        self._audit("state", job, {"from": str(old), "to": str(state)})
        await self._save(job)

    async def _done(self, job: Job) -> None:
        job.outcome = "done_verified"
        job.pending = None
        await self._move(job, S.DONE)
        self._finish(job)

    async def _fail(self, job: Job, message: str, outcome: str = "failed") -> None:
        if job.terminal:
            return
        job.error, job.outcome, job.pending, job.question = message, outcome, None, None
        if not job.summary or outcome != "failed":
            job.summary = message
        job.transition(S.FAILED, self.clock())
        self._audit("state", job, {"to": "failed", "error": message}, best_effort=True)
        await self._save(job)
        self._finish(job)

    async def _cancel(self, job: Job, message: str) -> None:
        if job.terminal:
            return
        job.error, job.outcome, job.pending, job.question = message, "cancelled", None, None
        job.summary = message
        job.transition(S.CANCELLED, self.clock())
        self._audit("state", job, {"to": "cancelled", "reason": message}, best_effort=True)
        await self._save(job)
        self._finish(job)

    def _finish(self, job: Job) -> None:
        job.timings_ms["total"] = int((self.clock() - job.created_at) * 1000)
        self.store.add_event(job.id, "job", job.outcome or str(job.state), job.timings_ms["total"],
                             outcome=job.outcome)
        self.store.save_job(job.to_dict())
        self._active.pop(job.id, None)

    async def _save(self, job: Job) -> None:
        self.store.save_job(job.to_dict())
        await self.notify.publish({"type": "job.update", "job": job.public()})

    def _audit(self, kind: str, job: Job | None, data: dict[str, Any], best_effort: bool = False) -> None:
        try:
            self.store.append_audit(kind, job.id if job else None, data)
        except Exception as e:
            if best_effort:
                log.error("audit write failed (%s): %s", kind, e)
                return
            raise AuditWriteError(str(e)) from e

    def _event(self, job: Job, stage: str, status: str, t0: float, **extra: Any) -> None:
        ms = int((self.clock() - t0) * 1000)
        job.timings_ms[stage] = job.timings_ms.get(stage, 0) + ms
        try:
            self.store.add_event(job.id, stage, status, ms, **extra)
        except Exception as e:  # noqa: BLE001 — metrics must never break the pipeline
            log.warning("event write failed: %s", e)
