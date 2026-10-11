# ADR-0003 — Public web access without Tailscale (2026-10-12)

## Context
The owner wants to use the voice remote from any browser at a normal URL, with Google login plus a key,
and without installing Tailscale on the phone. The app can act on a real PC, so internet exposure must be
compensated by stronger, layered authentication (doc §10, §20.4).

## Decision
```
Browser ──HTTPS──> Cloudflare Tunnel ──> PC1 127.0.0.1:8000 (pc.flukelnwza.online)
   1. Google OAuth (PKCE + state), only VPC_ALLOWED_EMAILS          -> vpc_session cookie (7 days)
   2. Secret Key once per device (vpc-cli set-pairing-key, rate-limited) -> vpc_device cookie (180 days, revocable)
   3. Every API call: session + device + X-Requested-With (CSRF); WebSocket: cookies + Origin check
   4. Bearer tokens disabled in public mode (VPC_ALLOW_BEARER=false)
PC2 agent ──wss (dials OUT)──> PC1 /agent/ws  (HMAC challenge; every command still HMAC-signed + verified)
```
- Cookies are HttpOnly + Secure + SameSite=Lax: page JavaScript never holds a credential.
- The Secret Key is stored only as a SHA-256 hash; rotating it doesn't log out already-paired devices.
- PC2 opens no inbound port and needs no VPN; a fake server can't forge commands because each request
  is signed with the shared secret and verified by the agent's existing policy layer.
- Tailscale serve routes removed. Ollama and the agent are not reachable from the internet.

## Residual risks
- Google account takeover alone is not enough (device key needed); a stolen *paired* phone is → unpair it
  from the app or `vpc-cli revoke-device`, and rotate the pairing key.
- Cloudflare terminates TLS (sees traffic). Acceptable for this home setup; revisit for sensitive data.
- Optional extra layer later: Cloudflare Access policy for the hostname.
