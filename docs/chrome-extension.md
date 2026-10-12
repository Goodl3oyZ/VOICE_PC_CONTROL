# Voice PC Chrome extension (PC2)

Redesign step 2. The agent drives your everyday, logged-in Chrome through a small extension instead of a
separate automated browser, so YouTube videos play and Google treats you as a normal user.

## Install (once)

1. In Chrome on PC2 open `chrome://extensions`, switch on **Developer mode** (top right).
2. **Load unpacked** → choose the `pc2-extension` folder of this repo.
3. Get the pairing token on PC2:
   ```
   cd pc2-agent
   ..\.venv\Scripts\python -m agent.ext_token
   ```
4. Click the extension's icon (pin it from the puzzle-piece menu) → paste the token → **Save**.
   The status turns to **Connected to the agent** while the agent is running.

The agent's `agent_config.local.json` uses `"browser_mode": "extension"` (default) and
`"extension_port": 8766`. Set `"browser_mode": "playwright"` to go back to the old automated browser.

## What it can and cannot do

| It can | It cannot |
| --- | --- |
| List the tabs of the current window, open an **https** page in a tab, switch to or close a tab | Open `file://`, `chrome://` or any non-https page |
| Read search results on Google and YouTube, read/press play on the YouTube video | Read or run scripts on any other site (host permissions: google.com and youtube.com only) |
| Talk to the agent on `ws://127.0.0.1:8766` | Talk to any other server; there is no "run this code" operation |

- The agent's bridge listens on 127.0.0.1 only, accepts only `chrome-extension://` origins, and requires the
  token (kept in the agent's data dir as `extension_token`). Delete that file and restart the agent to rotate it.
- Turn it off any time: untick **Allow Voice PC to control Chrome** in the extension, or switch the
  extension off in `chrome://extensions`.
- Google or YouTube human checks are reported to the phone and never solved by the agent.
- Page titles and results are untrusted data: they are shown on the phone, never followed as instructions.
