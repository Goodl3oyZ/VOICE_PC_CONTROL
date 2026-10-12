const $ = (id) => document.getElementById(id);
const LABELS = {
  connected: ["Connected to the agent", "ok"], connecting: ["Connecting…", ""], disconnected: ["Agent not running", "bad"],
  "wrong-token": ["Wrong pairing token", "bad"], "no-token": ["Paste the pairing token below", "bad"], off: ["Turned off", "bad"],
};
async function showStatus() {
  const { state } = await chrome.storage.session.get("state");
  const [text, cls] = LABELS[state] || ["…", ""];
  $("status").textContent = text;
  $("status").className = "status " + cls;
}
chrome.storage.local.get(["port", "enabled", "token"]).then((s) => {
  if (s.port) $("port").value = s.port;
  $("enabled").checked = s.enabled !== false;
  if (s.token) $("token").placeholder = "saved (paste to replace)";
});
$("save").onclick = async () => {
  const next = { port: Number($("port").value) || 8766, enabled: $("enabled").checked };
  const token = $("token").value.trim();
  if (token) next.token = token;
  await chrome.storage.local.set(next);
  $("token").value = "";
  $("token").placeholder = "saved (paste to replace)";
};
chrome.storage.session.onChanged.addListener(showStatus);
chrome.runtime.sendMessage("status").catch(() => {}); // wakes the worker and reconnects
showStatus();
setInterval(showStatus, 1500);
