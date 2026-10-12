# Implementation checklist — ระบบสั่งงานคอมพิวเตอร์ด้วยเสียง

Source: `../ระบบสั่งงานคอมพิวเตอร์ด้วยเสียง.pdf` (Design Draft v2, 2026-10-11).
IDs (US-xxx, TC-xxx, FR/NFR, T1–T9) refer to chapters 17–20 of that document.

Legend: `[x]` done and covered by an automated test · `[~]` code exists but needs real hardware/manual check · `[ ]` not started

## Status (2026-10-11)
- Python: **134 tests pass** (unit, API, PC2 agent, PC1↔PC2 E2E with real HMAC); core/policy coverage **94 %** (NFR-10 target ≥ 85 %); ruff + bandit clean.
- PWA: typecheck + production build OK (50 KB gzip); 4 vitest tests pass.
- Live smoke test on this Windows machine: real PC2 agent + real PC1 server → heartbeat online, Thai command `สถานะเครื่อง` → `done` in 112 ms through HMAC; unsigned PC2 call → 401; no-token PC1 call → 401; audit chain verified. (Only read-only `get_status` was exercised — no app was launched.)
- Eval baseline (rules only, no LLM): tool accuracy 70 %, refusal 100 %, dangerous executed 0, clarify 0 % → the remaining cases need the real local LLM (Spike SP-2).

## Live deployment (2026-10-11)
- [x] PC1 = LXC 102 `ai-lxc` (Proxmox, GTX 1650 SUPER 4 GB): systemd `voice-pc-control`, venv in `/opt/voice-pc-control`, secrets in `/etc/voice-pc-control.env`, admin via `vpc-cli`
- [x] LLM = **Ollama 0.34.4** (`docker-compose.yml` at repo root) with **`gemma4-e2b-qat`** — benchmark winner, LLM p50 0.43 s / p95 0.82 s (ADR-0002); llama.cpp stopped
- [x] **Open WebUI v0.11.4** at `https://chat.<domain>` (Cloudflare tunnel; Tailscale route removed) — Google + GitHub OAuth, new users pending approval
- [x] STT = faster-whisper `small` int8 on CPU
- [x] ~~HTTPS via `tailscale serve`~~ → replaced by **public access at `https://pc.flukelnwza.online`** (ADR-0003): Cloudflare tunnel, Google OAuth (allowlisted email) + one-time Secret Key per device, CSRF + WebSocket origin checks, bearer disabled
- [x] PC2 agent dials **out** to `wss://pc.flukelnwza.online/agent/ws` (HMAC challenge); no open port, no VPN — verified connected
- [x] Public checks: anonymous/fake-token API calls → 401; Google login uses PKCE; 154 tests incl. real-socket relay E2E
- [ ] Add `https://pc.flukelnwza.online/auth/google/callback` to the Google OAuth client (user action), create Secret Key, first phone login
- [x] **Bug fixed — voice never worked in production:** faster-whisper 1.2.1 calls `av.open(metadata_errors=…)`, removed in PyAV 19 → every audio command failed with TypeError. Now decoded by our own PyAV code; verified on PC1 with PyAV 19.0.1 (webm/opus + Thai mp3, ~2.5 s)
- [x] **Bug fixed — stuck "clarifying" jobs** could never be cleared (lost from memory after a restart): startup recovery, per-job cancel (`POST /jobs/{id}/cancel` + button), questions expire after 5 min, Stop also clears stale jobs
- [x] New Phase-1 tools: `search_web` (Google / YouTube results in Chrome) and `media_control` (play/pause, next/previous, volume ±, mute via Windows media keys — works for YouTube and Spotify)
- [ ] Thai STT accuracy: Whisper `small` misheard "เปิด" in 1 of 3 synthetic clips (asks to confirm when confidence < 0.7). Next: record ~30 real commands, measure CER, try a larger/Thai-tuned Whisper

## Gate G1 status (2026-10-12): functionality complete, gate not formally passed yet
- [x] Tool accuracy ≥ 90 % on golden set with the real model (100 %), 0 dangerous commands executed
- [x] Security tests TC-S01/S02/S06/S11/S13-equivalent pass
- [ ] Real voice from the phone end-to-end (blocked by the PyAV bug until now — needs the owner's phone test)
- [ ] First-try success ≥ 85 % and p95 ≤ 8 s measured on real spoken commands
- [x] PC2 = this notebook: agent (now outbound to PC1, see below), secret in Credential Manager, auto-start task "VoicePC Agent"
- [x] Real network E2E: status 493 ms, open Notepad 872 ms (TC-F03), repeat → "already open" (TC-F04), calculator via URI, regedit + evil-site refused, no-token 401, audit chain OK
- [x] HTTPS E2E from PC2: shortcut 1.3 s; LLM commands (intent → Notepad/Calculator) 6–30 s incl. first load; ambiguous → asks back; dangerous → refused
- [ ] Phone test (mic over HTTPS, hold-to-talk, Stop) — TC-F01/F02/F08
- [ ] OAuth redirect URIs registered in Google/GitHub consoles (user action)
- [ ] Clarify rate 75 % → 80 % (few-shot prompt)

## Current target: Sprint 0 + Phase 1 (MVP, S1–S3, Gate G1)

Everything is built behind Ports & Adapters, so the full pipeline runs and is tested
with fakes (no GPU, no Ollama, no second PC needed). Real adapters are wired but need
the hardware decisions in chapter 13 (see "Open questions" below).

### Sprint 0 — Foundation
- [x] Monorepo layout per §15.3 (`contracts/`, `pc1-orchestrator/`, `pc2-agent/`, `mobile-pwa/`, `eval/`, `security/`, `infra/`, `docs/`)
- [x] Shared contracts: tool schemas + risk levels in one place (`contracts/`) — single source of truth
- [x] HMAC-SHA256 request signing (method|path|timestamp|nonce|sha256(body)), 30 s window, one-time nonce
- [~] US-801 `docker compose up` for PC1 (`infra/docker-compose.yml`) — written, not run on a Proxmox VM yet
- [~] US-802 Agent auto-start at logon (`pc2-agent/install-task.ps1`) — script written, not run
- [x] US-803 Device token create / revoke (CLI `python -m app.cli`) — TC-F28
- [~] US-804 Spike STT/LLM on real hardware — harness ready (`eval/run.py`), needs Ollama + faster-whisper installed and recorded audio
- [x] US-805 Threat model v1 (`security/THREAT_MODEL.md`, T1–T9)
- [x] CI pipeline (`.github/workflows/ci.yml`: ruff, pytest+coverage, bandit, pip-audit, gitleaks)

### Phase 1 — Core pipeline (PC1)
- [x] Job state machine §14.3 (created→transcribing→planning→routing→dispatching→verifying→done, clarifying, awaiting_confirm, failed, cancelled; terminal states locked)
- [x] Alias normalisation (Thai/transliterated → canonical) — US-203 / TC-F06
- [x] Level-1 shortcut planner (rule based "เปิด <app>", "หยุด") — skips the LLM
- [x] LLM planner via `LLMPort` (Ollama `/api/chat` with tools) + fake for tests; invalid JSON → retry once → fail politely (TC-R01)
- [x] Tool Router / policy deny-by-default: unknown tool, bad args, enum allowlist, kill switch, rate limit, taint, risk ≥3 → confirm (TC-F05, TC-S05, TC-S06, TC-S11)
- [x] args_hash binds confirmation to exact arguments (TC-S16)
- [x] Confirm card + timeout → cancelled (TC-F11 logic; no risk-3 tools enabled yet in Phase 1)
- [x] Low STT confidence → clarifying "ใช่ไหม?" before LLM (US-102 / TC-F07)
- [x] Text command fallback, same pipeline (US-104)
- [x] Stop: cancels jobs + calls PC2 stop (US-103 / TC-F08 logic)
- [x] Thai summary built from *verified* result, never guessed (US-205)
- [x] SQLite store (WAL): jobs, events (timings per stage §21.3), audit log with hash chain (TC-S10)
- [x] Fail closed when audit can't be written (TC-R05)
- [x] PC2 offline detection via heartbeat, clear error instead of hanging (US-702 / TC-F17)
- [x] Circuit breaker after 3 consecutive PC2 failures (§14.7)
- [x] History endpoint, newest first, 50 items (US-701 / TC-F18)
- [x] REST + WebSocket API: `POST /command`, `POST /command/audio`, `GET /jobs`, `GET /jobs/{id}`, `POST /jobs/{id}/reply`, `POST /confirm/{id}`, `POST /stop`, `GET /status`, `WS /events`
- [x] Bearer token on every request, 401 and no job created (US-601 / TC-F22)
- [~] faster-whisper STT adapter — written, needs `pip install faster-whisper` + model on PC1

### Phase 1 — Windows Agent (PC2)
- [x] Agent API with HMAC verification, replay/old-timestamp rejection (US-602 / TC-S01, TC-S02)
- [x] Client IP allowlist (only PC1/VPN)
- [x] Idempotency key cache — retries don't run a tool twice (TC-R04)
- [x] Second policy check on PC2 (allowlist, args, kill switch, rate limit)
- [x] `open_app` (no shell, list argv or registered URI), already-running is idempotent (TC-F04)
- [x] `open_url` https-only + host allowlist (US-202 / TC-F23)
- [x] `get_status`, `stop_all`, kill switch on/off endpoint
- [x] Post-action verification (process appears) — reports failure instead of fake success (FR-05)
- [x] Local audit log (JSONL, hash chain)
- [x] Runs on a real Windows session (agent started, signed `get_status` worked live)
- [~] TC-F03 real app launch (`เปิดโครม` → Chrome window within 5 s) — not run yet; check `agent_config.json` paths first
- [~] US-607 hotkey/tray kill switch — CLI `python -m agent.killswitch on|off` done; tray/hotkey is Sprint 10

### Phase 1 — Mobile PWA
- [x] Served by PC1 from `mobile-pwa/dist` (verified live); manual manifest + shell-only service worker (ADR-005)
- [x] React + TypeScript + Vite PWA: hold-to-talk (MediaRecorder), text input, big Stop button, status, history, confirm card, clarify reply
- [x] All output rendered as text (React escaping, no `dangerouslySetInnerHTML`) — TC-S15
- [~] HTTPS + mic on a real phone through Caddy/Tailscale (SP-4 / TC-F01, TC-F02) — needs the network set up

### Eval
- [x] Golden dev set, 30 Thai commands (incl. negative + ambiguous) — `eval/golden/dev.jsonl`
- [x] Harness: tool accuracy, parameter exact-match, refusal, clarify rate, p50/p95 latency; CER function
- [ ] Recorded audio (3 conditions) for CER — needs your voice recordings
- [ ] Locked test set (100 sentences) for Gate G1

## Gate G1 (end of Phase 1) — not yet evaluated
- [ ] Tool accuracy ≥ 90 % on the real model
- [ ] First-try success ≥ 85 %
- [ ] p95 ≤ 8 s end-to-end on real hardware
- [x] Security tests TC-S01, S02, S06, S11 pass (automated); [ ] TC-S07 port scan, [ ] TC-S13 CI dep scan run in real CI

## English-only mode (2026-10-12) — done
- [x] `VPC_LANGUAGE=en`: Whisper auto-detects language; non-English speech/text rejected ("Only English is supported…"); English shortcuts, LLM prompt, results and errors; Thai kept behind `VPC_LANGUAGE=th`
- [x] PWA fully English + permanent "English only" notice (main screen + sign-in)
- [x] English golden set (`eval/golden/dev_en.jsonl`) on gemma4-e2b-qat: tool 95 %, refusal 100 %, clarify 100 %, LLM p50 0.45 s
- [x] Real English speech (Windows TTS clips) → correct commands on PC1; Thai speech → rejected; Stop never asks for confirmation

## Phase 2 (S4–S6) — in progress
- [x] Agent browser: Playwright driving installed Chrome, **dedicated profile** `<agent data>/chrome-profile`, visible window, single worker thread (US-304)
- [x] `web_search` — Bing results read in the agent browser, top results with real site names returned to the phone (US-301: 3.2 s, ≥3 links ✅)
- [x] `open_result N`, `browser_tabs` list/next/previous/close (US-303)
- [x] `youtube_play` — searches YouTube, clicks the first video, verifies it is **playing**
- [x] CAPTCHA detection → stop and report, never bypass (US-305); Google's automated-search CAPTCHA is avoided by reading Bing instead
- [x] Web results marked **untrusted** → job tainted → later risk ≥ 2 actions need confirmation (mechanism, US-604)
- [x] Live E2E through PC1 relay: search → open result → tabs → play → pause → close tab
- [x] **Tab reuse:** searching never opens a new tab when a search tab is already open (`choose_tab()`, 9 unit cases + 5 agent tests + live real-Chrome test: 3 searches = 1 tab; + YouTube = 2 tabs). Search never overwrites a page the user opened. Old `search_web` (new tab in the user's Chrome per search) disabled
- [x] **Bugs fixed (seen live):** (1) agent Chrome ran with `--no-sandbox` (Playwright default) → `chromium_sandbox=True`, verified 0 processes with the flag; (2) a YouTube search reused the playing tab and stopped the music → separate player/results tabs (`choose_youtube_tab()`), live test: music keeps playing through searches, one player only; (3) `TargetClosedError` after the agent window was closed → relaunch + retry once
- [x] Google blocks automated browsers with a CAPTCHA (even headed) → web search read **Bing** (superseded by the Chrome extension in the app-flows redesign: Google in the user's own Chrome)
- [x] **"What can I say?" guide**: `GET /capabilities` (apps/sites from knowledge) → PWA "All commands…" with 38 tap-to-run examples, allowed lists, refused list; voice "help"/"what can I say". Test parses every example and checks the policy allows it
- [ ] US-302 read & summarise a page with the LLM (untrusted content handling)
- [ ] US-603 confirm card UI for risk-3 tools (backend done in Phase 1) + first risk-3 tool
- [ ] US-401/402 files & Office (new file, original untouched)
- [ ] Spotify: specific song/playlist needs Spotify Web API (Premium for playback) — Spotify not installed on PC2 yet
- [ ] US-606 secrets canary test, US-608 red-team ≥ 30 prompt-injection cases, US-703 KPI dashboard → Gate G2

## Phase 3 (S7–S10) — done (Gate G3: 80 % on 10 hidden-check code tasks, revert 100 %, main untouched 100 %)
- [x] Coding tools on PC2 (list/read/search/git_status/edit/run_tests/diff/revert/open_project), ai/* branch + checkpoint commits, never touches uncommitted user work
- [x] Multi-step coding loop on PC1, honest "Not finished" report, phone diff/tests/revert panel
- [x] PC2 hotkey kill switch (Ctrl+Alt+Shift+K), audit export (`vpc-cli export-audit`, `GET /audit/export`, Settings download)

## Phase 4 (S11–S14) — in progress
- [x] Wake word + hands-free (30/30, 0 false accepts), spoken Stop, TTS replies, vision `look_at_screen`, Wake-on-LAN (awake path tested)
- [x] Red-team 35 cases: 32 blocked. **Fixed (2026-10-12):** I03/I07 — an AI edit adding process/network/secret/dynamic-code access or touching build/test config now needs the owner's approval (PC1 asks with the reason; PC2 denies without the approval hash), before any test runs
- [x] D03 ("Open cmd" opened Explorer): shells and admin tools are refused by rule before the LLM, unless allowlisted
- [x] Red-team re-run live (2026-10-12): **37/37** (direct 24/24, indirect 8/8, guard 2/2, web 2/2, screen 1/1). I03/I07 turned out to be judge false alarms (the model removed or kept the planted text; the judge read `old_text`) — judge fixed and unit-tested. New guard cases G01/G02 (urllib / subprocess on request) are held for approval live
- [x] 8-hour soak on PC1 (2026-10-12): **288/288 commands OK (100 %)**, p50 0.61 s, p95 0.70 s, RSS flat 815–826 MB
- [ ] TC-S09 kill switch with PC1 cut, real WoL from sleep, final security audit, Gate G4 write-up

## App flows redesign (design doc approved 2026-10-12)
- [x] Step 1 — flow engine on PC1 (`app/core/flows.py`, `GET /flows`, `POST /flows/{id}/run|control`, text-only `POST /stt`), Apps tab with wizard screens, voice answers ("the second one"), remember-last-used, "open YouTube"/"open Cursor" opens the wizard
- [x] Step 2a — Voice PC Chrome extension (`pc2-extension/`, `docs/chrome-extension.md`) driving the user's own Chrome; verified live: YouTube search + play (playing), CAPTCHA reported, non-https refused
- [x] Step 2b — extension loaded in the owner's Chrome and connected; live via PC1: YouTube play (playing), Google search (no CAPTCHA), tabs
- [ ] Step 2c — owner tries YouTube/Search from the phone Apps tab (checkpoint); then remove the Playwright browser
- [ ] Step 3 — Cursor flow (needs `agent login`); spike: `-p` has shell access, gated only by `--force` / `.cursor/cli.json` allow-deny → deny-by-default + approve + `--resume`
- [ ] Step 4 — social (FB, IG, X, TikTok) with approval cards and hourly limit
- [ ] Step 5 — Office, Steam, OBS
- [ ] Step 6 — polish, archify onboarding guide, Phase 4 wrap-up

## Open questions (chapter 13) — needed before real deployment
1. PC1: GPU/VRAM and which VM/LXC on Proxmox? (This dev machine shows a GTX 1650 4 GB → §11.1 suggests Whisper small/medium int8 + a ~3–4B 4-bit LLM, loaded alternately.)
2. PC2: Windows 10 or 11?
3. First input mode (push-to-talk assumed) and network (LAN vs Tailscale/WireGuard)?
4. Your top-10 apps and real paths for the allowlist/aliases (`pc1-orchestrator/data/knowledge.json`, `pc2-agent/agent_config.json`).
