import { useEffect, useState } from "react";
import { WifiOffIcon } from "./Icons";

export function OfflineBanner() {
  const [isOnline, setIsOnline] = useState(() => (typeof navigator !== "undefined" ? navigator.onLine : true));

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (isOnline) return null;

  return (
    <div className="offline-banner" role="alert">
      <WifiOffIcon size={18} />
      <div className="offline-text">
        <strong>You are offline</strong>
        <span>Voice commands need an internet connection to reach PC1.</span>
      </div>
    </div>
  );
}
