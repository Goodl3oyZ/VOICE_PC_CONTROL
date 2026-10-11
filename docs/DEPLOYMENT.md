# Deployment & Operations Guide

How the live system is installed on PC1 (Proxmox) and PC2 (Windows notebook), how to update it,
operate it, and fix the problems we already hit. No secrets are stored in this repo — every secret
lives in a root-only env file on PC1 or in Windows Credential Manager on PC2.

Design decisions behind this setup: [ADR-0002](adr/0002-ollama-gemma4-e2b.md) (Ollama + model choice),
[ADR-0003](adr/0003-public-web-access.md) (public web access, Google login + device key, agent relay).

---

## 1. Architecture

```
            Internet                              PC1 = Proxmox host → LXC 102 "ai-lxc" (Ubuntu 24.04)
┌──────────────────────┐   Cloudflare Tunnel   ┌─────────────────────────────────────────────────────┐
│ Phone / browser       │──────────────────────▶│ cloudflared (systemd)                               │
│  pc.<domain>          │                       │  pc.<domain>   → 127.0.0.1:8000  voice-pc-control   │
│  chat.<domain>        │                       │  chat.<domain> → 127.0.0.1:8080  open-webui (docker)│
└──────────────────────┘                       │                                                     │
                                                │ voice-pc-control (systemd, user vpc)                │
┌──────────────────────┐  wss (dials OUT)       │   PWA + REST/WebSocket API + /agent/ws              │
│ PC2 Windows notebook  │──────────────────────▶│   faster-whisper (CPU) → Ollama → policy → relay    │
│  VoicePC Agent task   │  pc.<domain>/agent/ws │ ollama (docker, GPU GTX 1650 SUPER 4 GB)            │
│  no open port, no VPN │                       │   127.0.0.1:11434, model gemma4-e2b-qat             │
└──────────────────────┘                       └─────────────────────────────────────────────────────┘
```

| Who may do what | How it is enforced |
|---|---|
| Use the voice remote | Google login (allow-listed email) **and** a device paired once with the Secret Key; CSRF header; WebSocket Origin check |
| Use Open WebUI | Open WebUI accounts (Google/GitHub OAuth); new users are `pending` until the admin approves |
| Send commands to PC2 | Only PC1, via the agent's outbound WebSocket; every request HMAC-signed (timestamp + one-time nonce) and re-checked by the agent's allowlist/policy |
| Reach Ollama / the agent | Nobody from outside: Ollama listens on 127.0.0.1, the agent listens nowhere |

## 2. What lives where

### PC1 (LXC 102 on Proxmox)
| Path / name | What |
|---|---|
| `/opt/voice-pc-control/` | App code (`contracts/`, `pc1-orchestrator/`, `mobile-pwa/dist/`, `eval/`), `.venv/`, `docker-compose.yml` |
| `/opt/voice-pc-control/.env` | Secrets for the docker stack (Open WebUI URL/secret key, OAuth clients) — `chmod 600` |
| `/etc/voice-pc-control.env` | Secrets/settings for the orchestrator service — `chmod 640 root:vpc` ([example](../infra/pc1/voice-pc-control.env.example)) |
| `/etc/systemd/system/voice-pc-control.service` | Orchestrator service ([copy](../infra/pc1/voice-pc-control.service)) |
| `/usr/local/bin/vpc-cli` | Admin helper ([copy](../infra/pc1/vpc-cli)) |
| `/var/lib/vpc/vpc.sqlite3` | Jobs, events, hash-chained audit log, paired devices, hashed Secret Key |
| `/etc/cloudflared/config.yml` | Tunnel ingress ([excerpt](../infra/cloudflared/ingress-example.yml)) |
| docker volumes `voice-pc-control_ollama`, `voice-pc-control_open-webui` | Ollama models, Open WebUI users/chats |
| `~/llama-cpp/` | Previous llama.cpp stack — **stopped**, `restart=no`, kept for rollback |

### PC2 (Windows notebook)
| Path / name | What |
|---|---|
| `<repo>\pc2-agent\` | Agent code, run directly from the repo |
| `<repo>\pc2-agent\agent_config.local.json` | Live config (gitignored): app allowlist, `pc1_ws_url` |
| `%LOCALAPPDATA%\voice-pc-agent\` | `agent.log`, `audit.jsonl` (hash chain), `killswitch.flag`, `chrome-profile\` (agent browser, separate from your own Chrome profile) |
| Credential Manager → `voice-pc-control` / `pc2_secret` | HMAC secret (same value as `VPC_PC2_SECRET` on PC1) |
| Task Scheduler → **VoicePC Agent** | Starts the agent at logon in the user session (not a service: UI automation needs the desktop) |

## 3. First-time setup

### 3.1 PC1 — AI stack (Ollama + Open WebUI)
```bash
cd /opt/voice-pc-control
cp .env.example .env && chmod 600 .env       # fill WEBUI_URL, WEBUI_SECRET_KEY, OAuth client IDs/secrets
docker compose --env-file .env up -d ollama open-webui
docker exec ollama ollama pull hf.co/google/gemma-4-E2B-it-qat-q4_0-gguf
docker exec ollama ollama cp hf.co/google/gemma-4-E2B-it-qat-q4_0-gguf:latest gemma4-e2b-qat
docker exec ollama ollama pull hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M   # optional fallback
```
Then open `https://chat.<domain>` and **create the admin account immediately** — the first account
becomes admin and the site is public.

### 3.2 PC1 — orchestrator service
On the dev machine (repo root), build the PWA and a bundle:
```powershell
cd mobile-pwa; npm ci; npm run build; cd ..
tar -czf vpc_bundle.tgz --exclude=__pycache__ --exclude="*.sqlite3*" contracts pc1-orchestrator mobile-pwa/dist eval infra docker-compose.yml requirements.txt
```
Copy `vpc_bundle.tgz` to PC1 (e.g. `scp` to the Proxmox host, then `pct push 102 ...`) and run:
```bash
mkdir -p /tmp/vpc && tar -xzf vpc_bundle.tgz -C /tmp/vpc infra   # only to get the deploy script the first time
sudo bash /tmp/vpc/infra/pc1/deploy.sh vpc_bundle.tgz
# first run creates /etc/voice-pc-control.env from the example and stops: fill it in, then run again
```
Copy `pc1-orchestrator/data/knowledge.json` to `knowledge.live.json` and keep **only the apps that exist
on PC2** (the same names as in the agent config).

Create the Secret Key for pairing browsers (shown once):
```bash
vpc-cli set-pairing-key
```

### 3.3 PC1 — Cloudflare tunnel
Add the hostnames to `/etc/cloudflared/config.yml` as in
[ingress-example.yml](../infra/cloudflared/ingress-example.yml), then:
```bash
cloudflared --config /etc/cloudflared/config.yml tunnel ingress validate
cloudflared tunnel route dns <TUNNEL-UUID> pc.<domain>
systemctl restart cloudflared
```

### 3.4 Google OAuth (one client can serve both apps)
Google Cloud Console → APIs & Services → Credentials → your **Web application** OAuth client:
- Authorized JavaScript origins: `https://pc.<domain>`, `https://chat.<domain>`
- Authorized redirect URIs:
  - `https://pc.<domain>/auth/google/callback`  (voice remote)
  - `https://chat.<domain>/oauth/google/callback`  (Open WebUI)
- If the consent screen is in *Testing*, add your Gmail as a test user.

GitHub (Open WebUI only): an OAuth App has **one** callback URL — create a dedicated app with
`https://chat.<domain>/oauth/github/callback`. Facebook login is not supported by Open WebUI.

### 3.5 PC2 — Windows agent
```powershell
cd <repo>
python -m venv .venv; .venv\Scripts\pip install -r requirements.txt keyring playwright==1.63.0
# store the shared HMAC secret (same value as VPC_PC2_SECRET on PC1)
.venv\Scripts\python -c "import keyring,getpass; keyring.set_password('voice-pc-control','pc2_secret', getpass.getpass())"
copy pc2-agent\agent_config.json pc2-agent\agent_config.local.json   # edit apps + pc1_ws_url
powershell -ExecutionPolicy Bypass -File pc2-agent\install-task.ps1
Start-ScheduledTask -TaskName "VoicePC Agent"
Get-Content $env:LOCALAPPDATA\voice-pc-agent\agent.log -Tail 5   # expect "connected to PC1 at wss://..."
```

### 3.6 Phone
Open `https://pc.<domain>` → **Sign in with Google** → enter the Secret Key once → *Add to Home Screen*.

## 4. Configuration reference

### `/etc/voice-pc-control.env` (orchestrator)
| Variable | Value on ai-lxc | Notes |
|---|---|---|
| `VPC_LANGUAGE` | `en` | English-only: Whisper auto-detects the language, non-English commands are rejected; `th` = Thai pipeline |
| `VPC_STT_CONF_MIN` | `0.55` | below this Whisper confidence the app asks "I heard … is that right?" (never for Stop) |
| `VPC_STT` / `VPC_STT_DEVICE` / `VPC_WHISPER_MODEL` | `faster_whisper` / `cpu` / `small` | GPU is left to the LLM |
| `VPC_LLM` / `VPC_OLLAMA_MODEL` | `ollama` / `gemma4-e2b-qat` | benchmark winner (ADR-0002) |
| `VPC_PC2` | `relay` | agent dials in to `/agent/ws`; `http` = old direct mode |
| `VPC_PC2_SECRET` | 64 hex chars | must equal PC2's Credential Manager value |
| `VPC_PUBLIC_URL` | `https://pc.<domain>` | used for the OAuth redirect URI and Secure cookies |
| `VPC_SESSION_SECRET` | 64 hex chars | signs login cookies; changing it logs everyone out |
| `VPC_GOOGLE_CLIENT_ID/SECRET` | OAuth web client | |
| `VPC_ALLOWED_EMAILS` | comma-separated | only these Google accounts can sign in |
| `VPC_ALLOW_BEARER` | `false` | keep false when public; `true` only for local CLI testing |

### `docker-compose.yml` (repo root) — Ollama tuned for a 4 GB card
| Setting | Value | Why |
|---|---|---|
| `OLLAMA_CONTEXT_LENGTH` | 16384 | Open WebUI sends 5–6k-token requests; gemma4 KV cache is tiny (~57 MB/slot) |
| `OLLAMA_NUM_PARALLEL` | 2 | voice commands don't wait behind a long chat answer |
| `OLLAMA_KV_CACHE_TYPE` / `OLLAMA_FLASH_ATTENTION` | `q8_0` / `1` | less VRAM |
| `OLLAMA_MAX_LOADED_MODELS` / `OLLAMA_KEEP_ALIVE` | 1 / 30m | keep one model warm |
| `DEFAULT_MODELS`, `TASK_MODEL` (Open WebUI) | `gemma4-e2b-qat` | titles/tags reuse the loaded model |
| `DEFAULT_USER_ROLE` | `pending` | public site: approve new users manually |

Measured: gemma4-e2b-qat at 16k = 2.8 GB VRAM, 100% GPU; voice routing p50 0.46 s idle, 1.6 s while a chat runs.

## 5. Updating

| What changed | Do this |
|---|---|
| PC1 Python / PWA code | build bundle (§3.2) → copy → `sudo bash infra/pc1/deploy.sh vpc_bundle.tgz` |
| `docker-compose.yml` | copy to `/opt/voice-pc-control/` → `docker compose --env-file .env up -d --force-recreate <service>` (volumes keep data) |
| Open WebUI `.env` (OAuth, URL) | edit `/opt/voice-pc-control/.env` → `docker compose --env-file .env up -d --force-recreate open-webui` |
| Orchestrator settings | edit `/etc/voice-pc-control.env` (keep trailing newline) → `systemctl restart voice-pc-control` |
| PC2 agent code/config | `git pull` on the notebook → `Stop-ScheduledTask` / `Start-ScheduledTask -TaskName "VoicePC Agent"` |
| Model | follow ADR-0002 "revisit": pull candidate → `python eval/run.py --llm ollama --model <m>` → compare → switch `VPC_OLLAMA_MODEL` + `DEFAULT_MODEL` |

Always run `pytest` and `ruff check .` locally before deploying.

## 6. Day-to-day operations

```bash
# PC1 (pct enter 102)
systemctl status voice-pc-control            # service state
journalctl -u voice-pc-control -f            # logs ("agent connected", job errors)
vpc-cli list-devices                         # paired browsers
vpc-cli revoke-device "<name>"               # lost phone → revoke now
vpc-cli set-pairing-key                      # rotate the Secret Key (paired devices stay paired)
vpc-cli verify-audit                         # audit hash chain intact?
docker compose -f /opt/voice-pc-control/docker-compose.yml ps
docker exec ollama ollama ps                 # loaded model, % GPU, context
docker logs --tail 50 open-webui
```
```powershell
# PC2
Get-Content $env:LOCALAPPDATA\voice-pc-agent\agent.log -Tail 20
.venv\Scripts\python -m agent.killswitch on      # emergency: refuse all actions (works without network)
.venv\Scripts\python -m agent.killswitch off
```

## 7. Troubleshooting (issues already seen)

| Symptom | Cause | Fix |
|---|---|---|
| Google `Error 400: redirect_uri_mismatch` | Redirect URI not registered in the OAuth client | Add exactly `https://<host>/auth/google/callback` (voice) or `/oauth/google/callback` (Open WebUI) — §3.4 |
| GitHub "redirect_uri is not associated with this application" | GitHub OAuth App allows one callback, it pointed elsewhere | Dedicated GitHub app for Open WebUI (§3.4) |
| Open WebUI `/auth?error=The email or password provided is incorrect` after OAuth | Login started on a different hostname than `WEBUI_URL` (state cookie on the wrong domain: `mismatching_state`) | Always open Open WebUI at its `WEBUI_URL` |
| Open WebUI `exceed_context_size_error` | Context too small for chat history | `OLLAMA_CONTEXT_LENGTH` ≥ 16384 |
| Voice commands take 7–30 s while chatting | One Ollama slot, voice queued behind chat | `OLLAMA_NUM_PARALLEL=2` |
| Model reloads (~25 s) when switching voice ↔ chat | Different clients requested different `num_ctx` | Never pass `num_ctx` from clients; use the server default |
| Chat answers show "Thinking…" and are slower | gemma4 thinking mode | Open WebUI → Admin → Models → Advanced Params → think off (voice already sends `think: false`) |
| Orchestrator crash: `could not convert string to float: '5VPC_...'` | Env file had no trailing newline, an appended line merged | Fix the line; `sed -i -e '$a\' /etc/voice-pc-control.env` |
| PC2 shows offline | Agent not running / can't reach PC1 | `agent.log`; restart the task; check `pc1_ws_url`; PC1 log should say `agent connected` |
| Agent: `could not bind` (old direct mode) | VPN interface down at logon | Use outbound mode (`pc1_ws_url`) — no binding needed |
| Host very slow, SSH times out | 8 GB host swapping (several models / large context / other services) | Keep one model loaded, 16k context, stop unused heavy services |
| Every voice command fails with `TypeError: open() got an unexpected keyword argument 'metadata_errors'` | faster-whisper 1.2.1 vs PyAV ≥ 19 | Fixed in code: audio is decoded by `decode_audio()` in our adapter (no dependency on faster-whisper's decoder) |
| Jobs stuck in "Waiting for your answer" | Unanswered questions / restart | Cancel button on the job card; auto-expire after 5 min; startup recovery; Stop clears all |
| "Only English is supported" | `VPC_LANGUAGE=en` and the command was not English | Speak/type English (by design) |
| Web search shows "CAPTCHA detected" | The search engine challenged the agent browser | By design the agent stops; solve it yourself on PC2. Google always challenges automated browsers, so searches use Bing |
| A new tab per search | (old behaviour of `search_web`) | Fixed: searches reuse the agent browser's search/YouTube tab; `search_web` disabled |
| Calculator/Notepad "verified" but window not visible | App opened then closed, or opened on another desktop | Check PC2 screen; the agent verifies the process exists |

## 8. Rollback

- **Back to llama.cpp:** `docker compose -f /opt/voice-pc-control/docker-compose.yml stop ollama` →
  `cd ~/llama-cpp && docker update --restart=unless-stopped llama-cpp && docker compose up -d` →
  set `VPC_LLM=openai`, `VPC_OPENAI_URL=http://127.0.0.1:10000`, `VPC_OPENAI_MODEL=<model>` and restart the service.
- **Orchestrator config:** `/etc/voice-pc-control.env.bak.*` and `/etc/cloudflared/config.yml.bak.*` are kept on each change.
- **Agent back to direct (Tailscale) mode:** remove `pc1_ws_url` from the agent config, set `VPC_PC2=http` + `VPC_PC2_URL` on PC1.

## 9. Security checklist

- [ ] Rotate any secret that was ever pasted into chat/email: OAuth client secrets, `VPC_PC2_SECRET`, Proxmox root password.
- [ ] `VPC_ALLOW_BEARER=false` and `VPC_ALLOWED_EMAILS` set to your address only.
- [ ] Open WebUI admin account exists; consider disabling email sign-up after setup.
- [ ] Ollama (11434), the orchestrator (8000) and Open WebUI (8080) bind to 127.0.0.1 only; only cloudflared publishes them.
- [ ] `vpc-cli verify-audit` OK; review `vpc-cli list-devices` monthly.
- [ ] Optional: Cloudflare Access policy in front of `pc.<domain>` for an extra login layer.
