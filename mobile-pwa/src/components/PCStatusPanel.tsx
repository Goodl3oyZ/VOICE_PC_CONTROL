import { LaptopIcon, WifiIcon, WifiOffIcon, StopIcon } from "./Icons";

interface PCStatusPanelProps {
  pc2Online: boolean | null;
  pc2Data: Record<string, unknown> | null;
  wsUp: boolean;
  totalJobs: number;
  activeJobsCount: number;
  onEmergencyStop: () => void;
}

export function PCStatusPanel({
  pc2Online,
  pc2Data,
  wsUp,
  totalJobs,
  activeJobsCount,
  onEmergencyStop,
}: PCStatusPanelProps) {
  return (
    <div className="pc-status-panel">
      <div className="panel-header">
        <div className="panel-title-group">
          <LaptopIcon size={18} />
          <h3>System status</h3>
        </div>
        <span className={`status-pill ${pc2Online ? "pill-online" : pc2Online === false ? "pill-offline" : "pill-pending"}`}>
          <span className={`pulse-dot ${pc2Online ? "green" : pc2Online === false ? "red" : "amber"}`} />
          {pc2Online ? "PC2 online" : pc2Online === false ? "PC2 offline" : "Checking…"}
        </span>
      </div>

      <div className="telemetry-grid">
        {/* PC2 Agent Link */}
        <div className="telemetry-card">
          <div className="telemetry-label">Controlled PC (PC2)</div>
          <div className="telemetry-value">
            {pc2Online ? (
              <span className="text-success">Connected, ready</span>
            ) : pc2Online === false ? (
              <span className="text-danger">Agent not connected</span>
            ) : (
              <span className="text-muted">Checking status…</span>
            )}
          </div>
          {pc2Data && Object.keys(pc2Data).length > 0 && (
            <div className="telemetry-extra">
              {Object.entries(pc2Data).slice(0, 3).map(([k, v]) => (
                <div key={k} className="extra-item">
                  <span>{k}:</span> <strong>{String(v)}</strong>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* PC1 Orchestrator Link */}
        <div className="telemetry-card">
          <div className="telemetry-label">Server link (PC1)</div>
          <div className="telemetry-value">
            {wsUp ? (
              <span className="text-success flex-align">
                <WifiIcon size={15} /> Live updates
              </span>
            ) : (
              <span className="text-warning flex-align">
                <WifiOffIcon size={15} /> Reconnecting…
              </span>
            )}
          </div>
          <div className="telemetry-extra">
            <div className="extra-item">
              <span>Active jobs:</span> <strong>{activeJobsCount}</strong>
            </div>
            <div className="extra-item">
              <span>Commands in history:</span> <strong>{totalJobs}</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Emergency Kill-Switch Callout */}
      <div className="killswitch-callout">
        <div className="callout-content">
          <div className="callout-heading">
            <StopIcon size={16} />
            <span>Emergency stop</span>
          </div>
          <p className="callout-text">
            If the computer is doing something wrong, or you want to cancel everything now, press stop.
          </p>
        </div>
        <button
          type="button"
          className="btn-killswitch"
          onClick={onEmergencyStop}
          aria-label="Emergency stop now"
        >
          <StopIcon size={16} />
          <span>Stop everything now</span>
        </button>
      </div>
    </div>
  );
}
