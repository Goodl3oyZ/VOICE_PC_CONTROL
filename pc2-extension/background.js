// Voice PC extension: a small, fixed set of operations for the Voice PC agent on THIS computer.
// It connects only to ws://127.0.0.1 (the agent), proves itself with the token from the options page,
// and has no "run arbitrary code" operation. Page scripts run only on Google and YouTube (host_permissions).

const VERSION = chrome.runtime.getManifest().version;
const DEFAULTS = { token: "", port: 8766, enabled: true };
let ws = null;
let state = "disconnected"; // disconnected | connecting | connected | wrong-token | off | no-token
let keepalive = null;
let retryMs = 2000;
let retryTimer = null;

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
      retryMs = 2000;
      setState("connected");
      clearInterval(keepalive);
      // Chrome keeps an MV3 worker alive only while its WebSocket carries messages at least every 30 s
      // (protocol pings do not count). Without an open extension page it was suspended ~20 s after
      // connecting, so: ping now and every 10 s (the agent also pings every 10 s).
      const ping = () => sock.readyState === WebSocket.OPEN && sock.send('{"type":"ping"}');
      ping();
      keepalive = setInterval(ping, 10000);
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
    if (state === "wrong-token") return;
    setState("disconnected");
    // The agent restarts after updates: retry soon (2 s, 4 s … 30 s) while this worker is alive; the
    // 1-minute alarm covers the time after Chrome stops the worker.
    clearTimeout(retryTimer);
    retryTimer = setTimeout(connect, retryMs);
    retryMs = Math.min(30000, retryMs * 2);
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
    case "ext.reload": // pick up a new version of these files after an update (reloads only itself)
      setTimeout(() => chrome.runtime.reload(), 200);
      return { reloading: VERSION };
    case "social.state":
      return runInPage(a.tabId, socialState, []);
    case "social.act": {
      const acts = ["like", "comment", "follow", "post", "message"];
      if (!acts.includes(a.action) || !["facebook", "instagram", "x", "tiktok"].includes(a.platform)) throw new Error("bad action");
      return runInPage(a.tabId, socialAct, [a.platform, a.action, String(a.text || "").slice(0, 500), !!a.dry]);
    }
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

// ------------------------------------------------------------------ social (only after approval on the phone)
function socialState() {
  const login = /\/(login|accounts\/login|i\/flow\/login|signup)/.test(location.pathname) ||
    !!document.querySelector("input[type=password]");
  return { url: location.href, loggedIn: !login };
}

// One fixed recipe per platform and action, found by stable labels. dry=true only reports whether the controls
// are there (nothing is typed or clicked). Every real action is checked on the page afterwards.
async function socialAct(platform, action, text, dry) {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const q = (sel) => document.querySelector(sel);
  const visible = (el) => !!el && el.getClientRects().length > 0;
  const byText = (sel, re) => [...document.querySelectorAll(sel)].find((el) => visible(el) && re.test(el.textContent.trim()));
  const wait = async (fn, ms = 8000) => {
    for (let t = 0; t < ms; t += 250) {
      const v = fn();
      if (v) return v;
      await sleep(250);
    }
    return null;
  };
  if (q("input[type=password]")) return { error: "Please log in on the PC first (the agent never types passwords)" };
  const type = async (el, value) => {
    el.focus();
    if (el.tagName === "TEXTAREA" || el.tagName === "INPUT") {
      const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set;
      setter.call(el, value);
      el.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      document.execCommand("insertText", false, value);
    }
    await sleep(400);
  };
  const enter = (el) => ["keydown", "keypress", "keyup"].forEach((k) =>
    el.dispatchEvent(new KeyboardEvent(k, { key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true })));
  const appears = (value) => wait(() => document.body.innerText.includes(value.slice(0, 60)), 8000);
  const MIND = /^What.s on your mind/;

  const R = {
    x: {
      like: { find: () => q("article [data-testid='like']") || q("article [data-testid='unlike']"),
              done: () => q("article [data-testid='unlike']") },
      follow: { find: () => q("[data-testid$='-follow']") || q("[data-testid$='-unfollow']"),
                done: () => q("[data-testid$='-unfollow']") },
      comment: { box: () => q("[data-testid='tweetTextarea_0']"), send: () => q("[data-testid='tweetButtonInline']") },
      post: { box: () => q("[data-testid='tweetTextarea_0']"), send: () => q("[data-testid='tweetButton']") },
      message: { open: () => q("[data-testid='sendDMFromProfile']"), box: () => q("[data-testid='dmComposerTextInput']"),
                 send: () => q("[data-testid='dmComposerSendButton']") },
    },
    facebook: {
      like: { find: () => q("[role='main'] [aria-label='Like'][role='button']") || q("[role='main'] [aria-label='Remove Like'][role='button']"),
              done: () => q("[role='main'] [aria-label='Remove Like'][role='button']") },
      follow: { find: () => q("[role='main'] [aria-label='Follow'][role='button']") || q("[role='main'] [aria-label='Following'][role='button']"),
                done: () => q("[role='main'] [aria-label='Following'][role='button']") },
      comment: { box: () => q("[contenteditable='true'][aria-label^='Write a comment']") || q("[contenteditable='true'][aria-label^='Comment as']"),
                 enter: true },
      post: { open: () => byText("[role='button']", MIND), box: () => q("[role='dialog'] [contenteditable='true'][role='textbox']"),
              send: () => q("[role='dialog'] [aria-label='Post'][role='button']") },
      message: { box: () => q("[contenteditable='true'][aria-label^='Message']") || q("[contenteditable='true'][role='textbox']"), enter: true },
    },
    instagram: {
      like: { find: () => q("main svg[aria-label='Like']") || q("main svg[aria-label='Unlike']"), done: () => q("main svg[aria-label='Unlike']") },
      follow: { find: () => byText("header button, header [role='button']", /^Follow$/) || byText("header button, header [role='button']", /^Following$/),
                done: () => byText("header button, header [role='button']", /^Following$/) },
      comment: { box: () => q("textarea[aria-label^='Add a comment']"), send: () => byText("[role='button'], button", /^Post$/) },
      message: { open: () => byText("header [role='button'], header button", /^Message$/),
                 box: () => q("[contenteditable='true'][aria-label^='Message']"), enter: true },
    },
    tiktok: {
      like: { find: () => q("[data-e2e='like-icon'], [data-e2e='browse-like-icon']"),
              done: () => q("[aria-pressed='true'] [data-e2e='like-icon'], [aria-pressed='true'][data-e2e='browse-like-icon']") },
      follow: { find: () => q("[data-e2e='follow-button'], [data-e2e='browse-follow']"),
                done: () => byText("[data-e2e='follow-button'], [data-e2e='browse-follow']", /^Following$/) },
      comment: { box: () => q("[data-e2e='comment-input'] [contenteditable='true']"), send: () => q("[data-e2e='comment-post']") },
    },
  };
  const r = (R[platform] || {})[action];
  if (!r) return { error: `${action} is not supported on ${platform}` };

  if (action === "like" || action === "follow") {
    const btn = await wait(r.find, dry ? 4000 : 8000);
    if (dry) return { dry: true, found: !!btn, already: !!r.done() };
    if (!btn) return { error: `Could not find the ${action} button on this page: open the post or profile first` };
    if (r.done()) return { ok: true, already: true };
    (btn.closest("button,[role='button']") || btn).click();
    return (await wait(r.done, 6000)) ? { ok: true } : { error: `The ${action} did not register` };
  }
  if (r.open && !r.box()) {
    const o = await wait(r.open, dry ? 4000 : 8000);
    if (dry) return { dry: true, found: !!o, step: "open" };
    if (!o) return { error: `Could not find where to start the ${action}` };
    o.click();
  }
  const box = await wait(r.box, dry ? 4000 : 8000);
  if (dry) return { dry: true, found: !!box, send: r.enter ? "enter" : !!(r.send && r.send()) };
  if (!box) return { error: `Could not find the ${action} box on this page` };
  await type(box, text);
  if (r.enter) {
    enter(box);
  } else {
    const send = await wait(() => {
      const b = r.send();
      return b && !b.disabled && b.getAttribute("aria-disabled") !== "true" ? b : null;
    });
    if (!send) return { error: "The send button stayed disabled" };
    send.click();
  }
  return (await appears(text)) ? { ok: true } : { error: `Sent, but the ${action} does not show on the page yet: check the PC` };
}

// ------------------------------------------------------------------ lifecycle
// Alarms do not always survive a Chrome restart: make sure the 1-minute reconnect alarm exists every time
// the worker starts (onInstalled alone missed it, so the extension stayed offline after an agent restart).
chrome.alarms.get("reconnect").then((a) => a || chrome.alarms.create("reconnect", { periodInMinutes: 1 }));
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
chrome.alarms.onAlarm.addListener((a) => a.name === "reconnect" && connect());
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (state === "wrong-token") state = "disconnected";
  if (ws) ws.close();
  ws = null;
  connect();
});
chrome.runtime.onMessage.addListener((msg, _sender, reply) => {
  if (msg === "status") {
    connect(); // opening the popup also reconnects right away
    reply({ state });
  }
});
connect();
