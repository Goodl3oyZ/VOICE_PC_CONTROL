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
          title={pc2Online ? "PC2 ออนไลน์" : "PC2 ไม่ได้เชื่อมต่อ"}
        >
          <span className="status-dot" />
          <span className="status-text">
            PC2 {pc2Online ? "ออนไลน์" : pc2Online === false ? "ออฟไลน์" : "…"}
          </span>
        </div>

        {!wsUp && (
          <div className="ws-reconnect-pill" title="ขาดการเชื่อมต่อ WebSocket กับ PC1">
            <WifiOffIcon size={13} />
            <span>เชื่อมต่อใหม่…</span>
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
          aria-label="หยุดคำสั่งทันที (Emergency Stop)"
          title="หยุดการทำงานคำสั่งทั้งหมดบน PC1 และ PC2 ทันที"
        >
          <StopIcon size={16} />
          <span className="stop-text">หยุด</span>
        </button>

        {/* PWA Install Button */}
        {canInstallPwa && onInstallPwa && (
          <button
            type="button"
            className="header-icon-button pwa-install-btn"
            onClick={onInstallPwa}
            aria-label="ติดตั้งแอปพลิเคชัน"
            title="ติดตั้ง Voice PC Remote เป็นแอปบนอุปกรณ์"
          >
            <DownloadIcon size={18} />
          </button>
        )}

        {/* Theme Toggle */}
        <button
          type="button"
          className="header-icon-button"
          onClick={onToggleTheme}
          aria-label={theme === "dark" ? "เปลี่ยนเป็นธีมสว่าง" : "เปลี่ยนเป็นธีมมืด"}
          title={theme === "dark" ? "สลับเป็นโหมดสว่าง" : "สลับเป็นโหมดมืด"}
        >
          {theme === "dark" ? <SunIcon size={18} /> : <MoonIcon size={18} />}
        </button>

        {/* Settings / Token modal trigger */}
        <button
          type="button"
          className="header-icon-button"
          onClick={onOpenSettings}
          aria-label="การตั้งค่าอุปกรณ์และโทเค็น"
          title="ตั้งค่า Device Token"
        >
          <SettingsIcon size={18} />
        </button>
      </div>
    </header>
  );
}
