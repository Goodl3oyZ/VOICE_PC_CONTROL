# Threat model v1 (US-805) — STRIDE over the trust boundaries

Source: design doc §20.1–20.5. Status column reflects **this codebase** as of v0.1 (Phase 1).

## Trust zones
1. **Phone (PWA)** — device token, mic, confirm card.
2. **PC1** — Gateway (auth) → STT → LLM planner (*untrusted component*) → Tool Router/policy → SQLite audit.
3. **PC2** — Agent API (HMAC, IP allowlist) → policy re-check → tools → local audit. Credentials stay here.
External content (web pages, files, search results) is **data, never instructions**.

## Threats and controls

| ID | Threat (STRIDE) | Controls in code | Test | Status |
|----|-----------------|------------------|------|--------|
| T1 | Stolen/lost phone token (S, E) | Hashed device tokens, per-device revoke (`app.cli revoke-device`), 401 on every route + WS | TC-F22, TC-F28 | Done. Biometric/PIN for risk ≥3 approvals: Phase 2 |
| T2 | Sniffing / MITM / rogue LAN device (I, T) | HTTPS via Caddy, VPN (Tailscale/WireGuard), no port-forward, agent binds VPN/LAN IP | TC-S07 (manual) | Config written, needs network setup |
| T3 | Fake/replayed voice (S) | Voice is never authentication; risk ≥3 needs tap-confirm on phone | TC-S12 | Logic done (no risk-3 tool enabled yet) |
| T4 | Prompt injection via web/files (T, E) | `untrusted` flag → job `tainted` → risk ≥2 needs confirm; tool output labelled UNTRUSTED in LLM context; React escapes all output; CSP | TC-S03, TC-S15 | Mechanism done; real web tools arrive in Phase 2 |
| T5 | LLM picks wrong/dangerous tool or args (E, R) | Pydantic schemas (extra=forbid), enum allowlist, deny-by-default router, PC2 re-check, args_hash binds approvals (TOCTOU), no shell | TC-S04/05/06/16 | Done |
| T6 | Direct calls to PC2 / replay (S, T) | HMAC-SHA256(method\|path\|ts\|nonce\|sha256(body)), ±30 s window, one-time nonce, client IP allowlist, idempotency keys | TC-S01, TC-S02, TC-R04 | Done |
| T7 | Secrets leak to LLM/logs (I) | Secrets only via env/keyring (Credential Manager); raw audio never stored; screenshots not implemented | TC-S08 (canary) | Partial — canary test due with browser tools (Phase 2) |
| T8 | Supply chain (T, E) | Pinned PWA deps, pip-audit / npm audit / bandit / gitleaks in CI | TC-S13 | CI written; pin Python hashes before prod |
| T9 | Over-privileged agent, log tampering, runaway loops, can't stop (R, D, E) | Agent runs as normal user; hash-chained audit on PC1 and PC2; rate limits both sides; loop guard (max steps, repeat detection, job timeout); kill switch file + API + Stop | TC-S09, TC-S10, TC-S11 | Done. Tray/hotkey: Sprint 10 |

## Fail-safe rules implemented
- Unknown tool / bad args / not in allowlist → **deny**, no second LLM attempt.
- Audit write fails before dispatch → **job fails, nothing sent to PC2** (TC-R05). PC2 returns 503 if its own audit fails.
- Tool reports `verified=false` → job **failed**, never "done" (FR-05, LLM09).
- PC2 offline / 3 consecutive failures → fail fast (heartbeat, circuit breaker).

## Residual risks (accepted for Phase 1)
- Tokens live in the PWA's `localStorage`; a compromised phone browser can use them → revoke quickly (RUNBOOK).
- WebSocket token passes as a query parameter (browser limitation) → only over HTTPS/VPN; Caddy access logs must not record query strings.
- Small local models will mis-plan sometimes → bounded by allowlist + verification + Stop.
