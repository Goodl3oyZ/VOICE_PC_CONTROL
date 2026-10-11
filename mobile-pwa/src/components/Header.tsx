import {
  DownloadIcon,
  LaptopIcon,
  MoonIcon,
  SettingsIcon,
  StopIcon,
  SunIcon,
  WifiOffIcon,
} from "./Icons";

interface HeaderProps {
  pc2Online: boolean | null;
  wsUp: boolean;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onOpenSettings: () => void;
  onEmergencyStop: () => void;
  canInstallPwa?: boolean;
  onInstallPwa?: () => void;
}

export function Header({
  pc2Online,
  wsUp,
  theme,
  onToggleTheme,
  onOpenSettings,
  onEmergencyStop,
  canInstallPwa,
  onInstallPwa,
}: HeaderProps) {
  return (
    <header className="app-header">
      {/* Brand & Connection Badges */}
      <div className="header-left">
        <div className="brand-logo-group">
          <div className="brand-icon-halo">
            <LaptopIcon size={20} className="brand-icon" />
          </div>
          <div className="brand-text">
            <span className="brand-name">Voice PC</span>
            <span className="brand-tag">Remote</span>
          </div>
        </div>

        {/* Live link status pill */}
        <div
          className={`link-status-pill ${
            pc2Online ? "online" : pc2Online === false ? "offline" : "pending"
          }`}
          title={pc2Online ? "PC2 online" : "PC2 not connected"}
        >
          <span className="status-dot" />
          <span className="status-text">
            PC2 {pc2Online ? "online" : pc2Online === false ? "offline" : "…"}
          </span>
        </div>

        {!wsUp && (
          <div className="ws-reconnect-pill" title="Lost the live connection to PC1">
            <WifiOffIcon size={13} />
            <span>Reconnecting…</span>
          </div>
        )}
      </div>

      {/* Header Actions */}
      <div className="header-right">
        {/* Sticky Emergency Kill Switch */}
        <button
          type="button"
          className="header-stop-button"
          onClick={onEmergencyStop}
          aria-label="Emergency stop"
          title="Stop everything on PC1 and PC2 now"
        >
          <StopIcon size={16} />
          <span className="stop-text">STOP</span>
        </button>

        {/* PWA Install Button */}
        {canInstallPwa && onInstallPwa && (
          <button
            type="button"
            className="header-icon-button pwa-install-btn"
            onClick={onInstallPwa}
            aria-label="Install app"
            title="Install Voice PC Remote on this device"
          >
            <DownloadIcon size={18} />
          </button>
        )}

        {/* Theme Toggle */}
        <button
          type="button"
          className="header-icon-button"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
          title={theme === "dark" ? "Light mode" : "Dark mode"}
        >
          {theme === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
        </button>

        {/* Settings / Token modal trigger */}
        <button
          type="button"
          className="header-icon-button"
          onClick={onOpenSettings}
          aria-label="Account and device"
          title="Account and device"
        >
          <SettingsIcon size={18} />
        </button>
      </div>
    </header>
  );
}
