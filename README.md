# Voice PC Control — ระบบสั่งงานคอมพิวเตอร์ด้วยเสียงผ่าน Local AI

Implementation of the design doc `../ระบบสั่งงานคอมพิวเตอร์ด้วยเสียง.pdf` (Design Draft v2).
Progress per story/test case: **[CHECKLIST.md](CHECKLIST.md)** · Server install, operations and
troubleshooting: **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** · Decisions: [docs/adr/](docs/adr/).

```
Browser/phone --HTTPS (Cloudflare tunnel)--> PC1 orchestrator <--wss (agent dials out)-- PC2 Windows agent
  Google login + one-time         faster-whisper -> aliases -> shortcut | Ollama   HMAC-verified requests,
  Secret Key per device           policy (deny by default) -> SQLite audit         allowlist, verify, audit
                                  Open WebUI (chat) shares the same Ollama
```

## Layout (doc §15.3)
| Path | What |
|------|------|
| `contracts/` | Tool schemas, risk levels, HMAC signing — shared by PC1 and PC2 |
| `pc1-orchestrator/app/core` | Domain: Job state machine, aliases, shortcuts, policy, use cases (no framework imports) |
| `pc1-orchestrator/app/ports`, `adapters` | Interfaces + real adapters (faster-whisper, Ollama, OpenAI-compatible, PC2 HTTP/relay, SQLite) and fakes |
| `pc1-orchestrator/app/api` | FastAPI REST + WebSocket for the phone, Google login + device pairing (`webauth.py`), `/agent/ws` |
| `pc2-agent/agent` | Agent API, policy, tool plugins, audit, kill switch, outbound connector |
| `mobile-pwa/` | React + TS PWA |
| `eval/` | Golden dataset + harness (tool accuracy, refusal, clarify, CER, p95) |
| `docker-compose.yml` | Ollama + Open WebUI (+ optional orchestrator container) |
| `infra/pc1/`, `infra/cloudflared/` | systemd unit, env example, `deploy.sh`, `vpc-cli`, tunnel ingress example |
| `security/`, `docs/` | Threat model, deployment guide, ADRs |

## Run locally (everything fake except the code paths)
```powershell
python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt pytest-timeout
.venv\Scripts\python -m pytest -q                      # 154 tests
cd mobile-pwa; npm ci; npm run build; cd ..
$env:PYTHONPATH="contracts;pc1-orchestrator"
$env:VPC_PUBLIC_URL="http://localhost:8000"; $env:VPC_SESSION_SECRET="dev-" + ("x" * 40)
$env:VPC_GOOGLE_CLIENT_ID="..."; $env:VPC_GOOGLE_CLIENT_SECRET="..."; $env:VPC_ALLOWED_EMAILS="you@gmail.com"
.venv\Scripts\python -m app.cli set-pairing-key       # Secret Key for the pairing screen
.venv\Scripts\python -m uvicorn app.main:build --factory --app-dir pc1-orchestrator --port 8000
# open http://localhost:8000 → Google → Secret Key → type "เปิดโน้ตแพด"
```
The Google client needs `http://localhost:8000/auth/google/callback` as a redirect URI for local testing.
Defaults are fake STT/LLM/PC2; switch with env vars (`pc1-orchestrator/app/settings.py`), e.g.
`VPC_STT=faster_whisper`, `VPC_LLM=ollama VPC_OLLAMA_MODEL=gemma4-e2b-qat`, `VPC_PC2=relay VPC_PC2_SECRET=...`.
API-only testing without a browser: leave `VPC_PUBLIC_URL` unset and use `python -m app.cli add-device` bearer tokens.

## Real deployment
Step-by-step in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**: PC1 AI stack (Ollama + Open WebUI), orchestrator
service (`infra/pc1/deploy.sh`), Cloudflare tunnel, Google OAuth, PC2 agent auto-start, phone pairing,
updates, operations (`vpc-cli`), troubleshooting and rollback.

Model choice: `python eval/run.py --llm ollama --model <m> --min-tool-acc 0.90` per candidate; record it as an ADR.

Emergency stop on PC2 without the network: `python -m agent.killswitch on`.
