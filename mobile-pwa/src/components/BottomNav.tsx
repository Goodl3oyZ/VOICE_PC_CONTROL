import { HomeIcon, HistoryIcon, SettingsIcon } from "./Icons";

export type NavTab = "home" | "activity" | "settings";

interface BottomNavProps {
  active: NavTab;
  onChange: (tab: NavTab) => void;
  activityCount?: number;
}

/** Fixed bottom navigation bar — Home / Activity / Settings. */
export function BottomNav({ active, onChange, activityCount = 0 }: BottomNavProps) {
  return (
    <nav className="bottom-nav" aria-label="Main navigation">
      <button
        type="button"
        className={`bottom-nav-item ${active === "home" ? "active" : ""}`}
        onClick={() => onChange("home")}
        aria-current={active === "home" ? "page" : undefined}
      >
        <HomeIcon size={22} />
        <span className="bottom-nav-label">Home</span>
      </button>

      <button
        type="button"
        className={`bottom-nav-item ${active === "activity" ? "active" : ""}`}
        onClick={() => onChange("activity")}
        aria-current={active === "activity" ? "page" : undefined}
      >
        <HistoryIcon size={22} />
        <span className="bottom-nav-label">Activity</span>
        {activityCount > 0 && (
          <span className="bottom-nav-badge" aria-label={`${activityCount} active`}>
            {activityCount}
          </span>
        )}
      </button>

      <button
        type="button"
        className={`bottom-nav-item ${active === "settings" ? "active" : ""}`}
        onClick={() => onChange("settings")}
        aria-current={active === "settings" ? "page" : undefined}
      >
        <SettingsIcon size={22} />
        <span className="bottom-nav-label">Settings</span>
      </button>
    </nav>
  );
}
