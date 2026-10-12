// Voice PC extension: a small, fixed set of operations for the Voice PC agent on THIS computer.
// It connects only to ws://127.0.0.1 (the agent), proves itself with the token from the options page,
// and has no "run arbitrary code" operation. Page scripts run only on Google and YouTube (host_permissions).

const VERSION = chrome.runtime.getManifest().version;
const DEFAULTS = { token: "", port: 8766, enabled: true };
let ws = null;
let state = "disconnected"; // disconnected | connecting | connected | wrong-token | off | no-token
let keepalive = null;

async function settings() {
  return { ...DEFAULTS, ...(await chrome.storage.local.get(["token", "port", "enabled"])) };
}

function setState(s) {
  state = s;
  chrome.storage.session.set({ state: s }).catch(() => {});
  chrome.action.setBadgeText({ text: s === "connected" ? "" : "!" }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ color: "#ef4444" }).catch(() => {});
}

async function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
  const s = await settings();
  if (!s.enabled) return setState("off");
  if (!s.token) return setState("no-token");
  const port = Number(s.port) || 8766;
  setState("connecting");
  const sock = new WebSocket(`ws://127.0.0.1:${port}/`);
  ws = sock;
  sock.onopen = () => sock.send(JSON.stringify({ type: "hello", token: s.token, version: VERSION }));
  sock.onmessage = async (ev) => {
    let msg;
    try {
      msg = JSON.parse(ev.data);
    } catch {
      return;
    }
    if (msg.type === "welcome") {
      setState("connected");
      clearInterval(keepalive);
      // An active WebSocket keeps the MV3 service worker alive (Chrome 116+) while messages flow.
      keepalive = setInterval(() => sock.readyState === WebSocket.OPEN && sock.send('{"type":"ping"}'), 20000);
      return;
    }
    if (msg.type === "rejected") {
      setState("wrong-token");
      return;
    }
    if (!msg.id || !msg.op) return;
    try {
      const data = await handle(msg.op, msg.args || {});
      sock.send(JSON.stringify({ id: msg.id, ok: true, data }));
    } catch (e) {
      sock.send(JSON.stringify({ id: msg.id, ok: false, error: String(e && e.message ? e.message : e), captcha: !!(e && e.captcha) }));
    }
  };
  sock.onclose = () => {
    clearInterval(keepalive);
    if (ws === sock) ws = null;
    if (state !== "wrong-token") setState("disconnected");
  };
}

// ------------------------------------------------------------------ operations
async function focusedWindow() {
  return chrome.windows.getLastFocused({ windowTypes: ["normal"] });
}

function requireHttps(url) {
  let u;
  try {
    u = new URL(url);
  } catch {
    throw new Error("bad url");
  }
  if (u.protocol !== "https:") throw new Error("only https pages can be opened");
  return u.href;
}

function waitComplete(tabId, timeoutMs) {
  return new Promise((resolve) => {
    const done = () => {
      chrome.tabs.onUpdated.removeListener(listener);
      clearTimeout(t);
      chrome.tabs.get(tabId).then(resolve, () => resolve(null));
    };
    const listener = (id, info) => id === tabId && info.status === "complete" && done();
    const t = setTimeout(done, timeoutMs);
    chrome.tabs.onUpdated.addListener(listener);
  });
}

const tabInfo = (t, focused) => ({ id: t.id, url: t.url || "", title: t.title || "", active: !!t.active, audible: !!t.audible, focused });

async function handle(op, a) {
  switch (op) {
    case "tabs.list": {
      const w = await focusedWindow();
      const tabs = await chrome.tabs.query({ windowId: w.id });
      return tabs.map((t) => tabInfo(t, !!w.focused));
    }
    case "tabs.open": {
      const url = requireHttps(a.url);
      let tab;
      if (a.tabId) {
        tab = await chrome.tabs.update(a.tabId, { url, active: true });
      } else {
        const w = await focusedWindow();
        tab = await chrome.tabs.create({ url, active: true, windowId: w.id });
      }
      await chrome.windows.update(tab.windowId, { focused: true }).catch(() => {});
      const t = (await waitComplete(tab.id, 20000)) || tab;
      return tabInfo(t, true);
    }
    case "tabs.activate": {
      const t = await chrome.tabs.update(a.tabId, { active: true });
      return tabInfo(t, true);
    }
    case "tabs.close":
      await chrome.tabs.remove(a.tabId);
      return {};
    case "page.results":
      return runInPage(a.tabId, extractResults, [a.kind === "youtube" ? "youtube" : "google", Math.min(10, Number(a.max) || 5)]);
    case "video.state":
      return runInPage(a.tabId, videoState, []);
    case "video.play":
      return runInPage(a.tabId, videoPlay, []);
    default:
      throw new Error(`unknown operation ${op}`);
  }
}

async function runInPage(tabId, func, args) {
  const [res] = await chrome.scripting.executeScript({ target: { tabId }, func, args });
  const r = res ? res.result : null;
  if (r && r.captcha) {
    const e = new Error("The site is asking to prove you are human. Please solve it on the PC; the agent will not.");
    e.captcha = true;
    throw e;
  }
  if (r && r.error) throw new Error(r.error);
  return r;
}

// ------------------------------------------------------------------ page functions (serialized into the page)
async function extractResults(kind, max) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const captcha = () =>
    location.pathname.startsWith("/sorry/") || !!document.querySelector("iframe[src*='recaptcha'], form#captcha-form");
  const text = (el) => (el ? el.textContent.replace(/\s+/g, " ").trim() : "");
  for (let i = 0; i < 40; i++) {
    if (captcha()) return { captcha: true };
    let out = [];
    if (kind === "youtube") {
      for (const r of document.querySelectorAll("ytd-video-renderer")) {
        const a = r.querySelector("a#video-title");
        if (!a || !a.href) continue;
        out.push({
          title: (a.getAttribute("title") || text(a)).slice(0, 200),
          url: a.href.slice(0, 500),
          host: "youtube.com",
          channel: text(r.querySelector("ytd-channel-name a")).slice(0, 100),
          length: text(r.querySelector("ytd-thumbnail-overlay-time-status-renderer #text, .badge-shape-wiz__text, .yt-badge-shape__text, badge-shape")).slice(0, 12),
        });
        if (out.length >= max) break;
      }
    } else {
      for (const h3 of document.querySelectorAll("#search a h3")) {
        const a = h3.closest("a");
        if (!a || !a.href.startsWith("https://")) continue;
        const host = new URL(a.href).hostname.replace(/^www\./, "");
        if (host.endsWith("google.com")) continue;
        out.push({ title: text(h3).slice(0, 200), url: a.href.slice(0, 1000), host });
        if (out.length >= max) break;
      }
    }
    if (out.length) return out;
    await sleep(250);
  }
  return [];
}

function videoState() {
  const v = document.querySelector("video");
  return v ? { exists: true, paused: v.paused || v.ended, time: v.currentTime } : { exists: false, paused: true, time: 0 };
}

async function videoPlay() {
  const v = document.querySelector("video");
  if (!v) return { exists: false };
  try {
    await v.play();
  } catch (e) {
    return { exists: true, paused: true, blocked: e.name };
  }
  return { exists: true, paused: v.paused };
}

// ------------------------------------------------------------------ lifecycle
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("reconnect", { periodInMinutes: 1 });
  connect();
});
chrome.alarms.onAlarm.addListener((a) => a.name === "reconnect" && connect());
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (state === "wrong-token") state = "disconnected";
  if (ws) ws.close();
  ws = null;
  connect();
});
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === "status") reply({ state });
});
connect();
