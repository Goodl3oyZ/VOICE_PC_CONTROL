import {
  DownloadIcon,
  LaptopIcon,
  MoonIcon,
  StopIcon,
  SunIcon,
} from "./Icons";

interface HeaderProps {
  pc2Online: boolean | null;
  wsUp: boolean;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onEmergencyStop: () => void;
  onOpenSettings?: () => void;
  canInstallPwa?: boolean;
  onInstallPwa?: () => void;
}

export function Header({
  pc2Online,
  wsUp,
  theme,
  onToggleTheme,
  onEmergencyStop,
  canInstallPwa,
  onInstallPwa,
}: HeaderProps) {
  return (
    <header className="app-header">
      {/* Brand & Connection Badge */}
      <div className="header-left">
        <div className="brand-logo-group">
          <div className="brand-icon-halo">
            <LaptopIcon size={18} className="brand-icon" />
          </div>
          <div className="brand-text">
            <span className="brand-name">Voice PC</span>
            <span className="brand-tag">Remote</span>
          </div>
        </div>

        {/* Single unified status pill */}
        {!wsUp ? (
          <div className="link-status-pill reconnecting" title="Lost connection to PC1 orchestrator">
            <span className="status-dot warning" />
            <span className="status-text">Reconnecting…</span>
          </div>
        ) : (
          <div
            className={`link-status-pill ${pc2Online ? "online" : pc2Online === false ? "offline" : "pending"}`}
            title={pc2Online ? "PC2 agent is connected and ready" : "PC2 agent offline"}
          >
            <span className="status-dot" />
            <span className="status-text">
              {pc2Online ? "PC2 Online" : pc2Online === false ? "PC2 Offline" : "Checking…"}
            </span>
          </div>
        )}
      </div>

      {/* Header Actions */}
      <div className="header-right">
        {/* Sticky Emergency STOP Switch */}
        <button
          type="button"
          className="header-stop-button"
          onClick={onEmergencyStop}
          aria-label="Emergency stop"
          title="Stop everything on PC1 and PC2 now"
        >
          <StopIcon size={14} />
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
            <DownloadIcon size={17} />
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
          {theme === "dark" ? <SunIcon size={17} /> : <MoonIcon size={17} />}
        </button>
      </div>
    </header>
  );
}

