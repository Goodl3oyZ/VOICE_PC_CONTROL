# ADR-0001…0007 — decisions taken while building v0.1

| ADR | Decision | Why | Revisit when |
|-----|----------|-----|--------------|
| 001 | Python on PC1 + PC2, TypeScript PWA (as doc ADR-001) | Shared contracts, Windows automation libraries | Packaging the agent becomes painful |
| 002 | Local LLM behind `LLMPort`, Ollama adapter first (doc ADR-002) | Privacy, no per-call cost | Spike SP-2 shows accuracy < 90 % |
| 003 | Tools-first, level-1 rule shortcuts before the LLM (doc ADR-003) | "เปิด X" needs no LLM: faster, deterministic. Eval baseline: rules alone hit 14/20 positive cases | — |
| 004 | Plain JSON function calling now, MCP wrapper later (doc §15.1) | Fewer moving parts; contracts are already JSON Schema | A second client needs the tools |
| 005 | Hand-written web manifest + service worker instead of `vite-plugin-pwa` | Keeps the PWA at 2 runtime deps (React) — smaller supply-chain surface (T8) | Need offline sync / push |
| 006 | PC1 polls PC2 `/status` every 5 s as the heartbeat (instead of PC2 pushing) | PC2 never needs credentials for PC1; same HMAC channel | Many PC2s |
| 007 | Phase 1 runs one tool per command (`multi_step=False`); ReAct loop is implemented behind the flag with loop guards | Small models + single-tool commands; ReAct is Phase 3 scope | Sprint 10 (US-506) |
| 008 | Agent kill switch is a flag file (`killswitch.flag`) | Survives restarts; flippable locally without network (`python -m agent.killswitch on`) | Tray/hotkey in Sprint 10 |
