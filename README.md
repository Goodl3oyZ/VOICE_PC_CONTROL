# Voice PC Control — ระบบสั่งงานคอมพิวเตอร์ด้วยเสียงผ่าน Local AI

Implementation of the design doc `../ระบบสั่งงานคอมพิวเตอร์ด้วยเสียง.pdf` (Design Draft v2).
Progress per story/test case: **[CHECKLIST.md](CHECKLIST.md)**.

```
Phone (PWA) --HTTPS+token--> PC1 orchestrator --HMAC over VPN--> PC2 Windows agent
  hold-to-talk                 faster-whisper -> aliases -> shortcut | Ollama   allowlist re-check
  Stop / confirm               policy (deny by default) -> SQLite audit         launch + verify + audit
```

## Layout (doc §15.3)
| Path | What |
|------|------|
| `contracts/` | Tool schemas, risk levels, HMAC signing — shared by PC1 and PC2 |
| `pc1-orchestrator/app/core` | Domain: Job state machine, aliases, shortcuts, policy, use cases (no framework imports) |
| `pc1-orchestrator/app/ports`, `adapters` | Interfaces + real adapters (faster-whisper, Ollama, PC2 HTTP, SQLite) and fakes |
| `pc1-orchestrator/app/api` | FastAPI REST + WebSocket for the phone |
| `pc2-agent/agent` | Agent API, policy, tool plugins, audit, kill switch |
| `mobile-pwa/` | React + TS PWA |
| `eval/` | Golden dataset + harness (tool accuracy, refusal, clarify, CER, p95) |
| `security/`, `docs/adr/`, `infra/` | Threat model, decisions, compose/Caddy |

## Run locally (everything fake except the code paths)
```powershell
python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt pytest-timeout
.venv\Scripts\python -m pytest -q                      # 134 tests
cd mobile-pwa; npm ci; npm run build; cd ..
$env:PYTHONPATH="contracts;pc1-orchestrator"
.venv\Scripts\python -m app.cli add-device phone1      # prints a token
.venv\Scripts\python -m uvicorn app.main:build --factory --app-dir pc1-orchestrator --port 8000
# open http://127.0.0.1:8000, paste the token, type "เปิดโน้ตแพด"
```
Defaults: fake STT/LLM/PC2. Switch with env vars (`pc1-orchestrator/app/settings.py`):
`VPC_STT=faster_whisper`, `VPC_LLM=ollama VPC_OLLAMA_MODEL=...`, `VPC_PC2=http VPC_PC2_URL=... VPC_PC2_SECRET=...`.

## Real deployment (after answering the open questions in CHECKLIST.md)
1. **PC2 (notebook):** `pip install -r requirements.txt keyring`, edit `pc2-agent/agent_config.json` (apps, `allowed_clients` = PC1 VPN IP, `bind_host` = VPN IP), store the secret in Credential Manager, run `pc2-agent/install-task.ps1`. Firewall: allow the port only from PC1.
2. **PC1 (Proxmox VM):** `cp infra/.env.example infra/.env`, fill it, `docker compose -f infra/docker-compose.yml up -d`, `docker compose exec ollama ollama pull qwen2.5:3b`.
3. **Phone:** open `https://<pc1-hostname>` over Tailscale, add to home screen, paste token.
4. **Spike/eval:** `python eval/run.py --llm ollama --model <m> --min-tool-acc 0.90` for each candidate model; record the choice as an ADR.

Emergency stop on PC2 without the network: `python -m agent.killswitch on`.
