import { useEffect, useState } from "react";
import { DownloadIcon, XIcon } from "./Icons";

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

export function InstallPrompt() {
  const [deferredPrompt, setDeferredPrompt] = useState<BeforeInstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    const handler = (e: Event) => {
      e.preventDefault();
      setDeferredPrompt(e as BeforeInstallPromptEvent);
    };

    window.addEventListener("beforeinstallprompt", handler);
    return () => window.removeEventListener("beforeinstallprompt", handler);
  }, []);

  if (!deferredPrompt || dismissed) return null;

  const handleInstall = async () => {
    await deferredPrompt.prompt();
    const choice = await deferredPrompt.userChoice;
    if (choice.outcome === "accepted") {
      setDeferredPrompt(null);
    }
  };

  return (
    <div className="install-prompt-banner" role="complementary" aria-label="Install app">
      <div className="install-prompt-content">
        <DownloadIcon size={20} className="install-icon" />
        <div className="install-prompt-text">
          <strong>Install Voice PC Remote</strong>
          <span>Full screen and fast, like a native app</span>
        </div>
      </div>
      <div className="install-prompt-actions">
        <button type="button" className="btn-install-confirm" onClick={handleInstall}>
          Install
        </button>
        <button
          type="button"
          className="btn-install-dismiss"
          onClick={() => setDismissed(true)}
          aria-label="Don't show again"
        >
          <XIcon size={16} />
        </button>
      </div>
    </div>
  );
}
