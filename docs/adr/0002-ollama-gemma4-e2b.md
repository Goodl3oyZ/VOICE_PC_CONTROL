# ADR-0002 — Ollama + Open WebUI, model gemma-4-E2B-it QAT (2026-10-11)

## Context
PC1 = LXC on Proxmox, GTX 1650 SUPER **4 GB VRAM**, 8 GB host RAM shared with other services.
The existing llama.cpp router (ctx 32768) answered in 11–76 s because of RAM pressure and the huge context.

## Decision
- Runtime: **Ollama 0.34.4** in Docker (`docker-compose.yml` at repo root), `OLLAMA_CONTEXT_LENGTH=4096`,
  flash attention, q8_0 KV cache, 1 model loaded. **Open WebUI v0.11.4** for chat, Google + GitHub OAuth,
  new users `pending` until approved. Both bound to 127.0.0.1, published only via `tailscale serve` HTTPS.
- Model: **`gemma4-e2b-qat`** = `hf.co/google/gemma-4-E2B-it-qat-q4_0-gguf` (Google official QAT q4_0).
  Fallback kept: `qwen3-4b-instruct` = `hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M`.
- llama.cpp container stopped with `restart=no` (files kept in `~/llama-cpp`).

## Evidence (eval/golden/dev.jsonl, 30 Thai commands, on the real GPU)
| Model | Tool | Refuse | Clarify | LLM p50 | LLM p95 | GPU fit |
|-------|------|--------|---------|---------|---------|---------|
| **gemma-4-E2B QAT** (warm ×2) | 100 % | 100 % | 75 % | **0.43 s** | **0.82 s** | 100 % GPU |
| Qwen3-4B-Instruct-2507 (warm ×2) | 100 % | 100 % | 75 % | 1.15 s | 2.74 s | 17 % CPU offload |
| Qwen3.5-4B (think off) | 100 % | 100 % | 0 % | 3.7 s | 9.9 s | 45 % CPU offload |
| Qwen3.5-2B | 100 % | 100 % | 0 % — guessed tools for ambiguous commands | 0.85 s | 1.7 s | 100 % GPU |

Candidates came from a HuggingFace survey of GGUF instruct models that fit 4 GB. Thai-specialised
Typhoon 2.1 (Gemma 3 base) was skipped: no tool-calling template in Ollama.

## Update — context 16k + 2 parallel slots (Open WebUI in production)
Open WebUI sent 5.5k-token requests → `exceed_context_size_error` at 4k. Measured on the card:
- 4k / 8k / 12k / 16k context all 100 % GPU (2.74 → 2.79 GB): gemma4 uses sliding-window attention,
  KV cache is only ~57 MB per 16k slot. → `OLLAMA_CONTEXT_LENGTH=16384`.
- Clients must not send their own `num_ctx` (a mismatch forces a ~25 s model reload); the orchestrator now uses the server default.
- Voice routing at 16k, idle: p50 0.46 s, p95 2.5 s (same accuracy). Behind a long Open WebUI answer with 1 slot:
  7–30 s and timeouts. → `OLLAMA_NUM_PARALLEL=2`: voice while a 6k-token chat generates = p50 1.6 s, p95 4.4 s
  (one 61 s outlier during the chat's prompt prefill). VRAM 2.82 GB.
- gemma4 thinks by default (~700 chars ≈ 4 s per answer in chat); the orchestrator sends `think: false`.

## Consequences / revisit when
- Clarify rate 75 % < 80 % target (TC-E05): add few-shot examples to the system prompt.
- Revisit when VRAM grows (8 GB+ → Qwen3-4B/8B at Q4 fully on GPU) or a new small Thai tool-calling model appears.
- Thai STT: try `typhoon-ai/typhoon-whisper-turbo` once a GPU slot is free (currently faster-whisper small on CPU).
