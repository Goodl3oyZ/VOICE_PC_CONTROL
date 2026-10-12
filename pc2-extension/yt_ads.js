// Voice PC: on YouTube, press YouTube's own "Skip" button as soon as it appears (setting "ytAutoSkip", on by
// default; background.js sends the real click). Optional "ytMuteAds": mute while an ad plays and restore
// afterwards. Unskippable ads are NOT fast-forwarded or blocked: only what YouTube itself offers is used.
(() => {
  const SKIP = ".ytp-skip-ad-button, .ytp-ad-skip-button, .ytp-ad-skip-button-modern, button[id^='skip-button']";
  let opts = { ytAutoSkip: true, ytMuteAds: false };
  let mutedByUs = false;

  chrome.storage.local.get(["ytAutoSkip", "ytMuteAds"]).then((s) => {
    opts = { ytAutoSkip: s.ytAutoSkip !== false, ytMuteAds: s.ytMuteAds === true };
  });
  chrome.storage.onChanged.addListener((c, area) => {
    if (area !== "local") return;
    if (c.ytAutoSkip) opts.ytAutoSkip = c.ytAutoSkip.newValue !== false;
    if (c.ytMuteAds) opts.ytMuteAds = c.ytMuteAds.newValue === true;
  });

  const tick = () => {
    const player = document.querySelector(".html5-video-player");
    const ad = !!player && player.classList.contains("ad-showing");
    const video = document.querySelector("video");
    if (ad && opts.ytAutoSkip) {
      const b = [...document.querySelectorAll(SKIP)].find((el) => el.getClientRects().length > 0);
      if (b) {
        // YouTube ignores script clicks (isTrusted=false), so the extension's worker sends a real click there.
        const r = b.getBoundingClientRect();
        chrome.runtime.sendMessage({ type: "yt.skip", x: r.left + r.width / 2, y: r.top + r.height / 2 }).catch(() => {});
      }
    }
    if (video && opts.ytMuteAds) {
      if (ad && !video.muted) {
        video.muted = true;
        mutedByUs = true;
      } else if (!ad && mutedByUs) {
        video.muted = false;
        mutedByUs = false;
      }
    }
  };
  setInterval(tick, 500);
})();
