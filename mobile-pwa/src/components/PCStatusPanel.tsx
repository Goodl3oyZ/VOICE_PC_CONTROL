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
          <h3>สถานะระบบและการเชื่อมต่อ</h3>
        </div>
        <span className={`status-pill ${pc2Online ? "pill-online" : pc2Online === false ? "pill-offline" : "pill-pending"}`}>
          <span className={`pulse-dot ${pc2Online ? "green" : pc2Online === false ? "red" : "amber"}`} />
          {pc2Online ? "PC2 ออนไลน์" : pc2Online === false ? "PC2 ออฟไลน์" : "กำลังตรวจสอบ…"}
        </span>
      </div>

      <div className="telemetry-grid">
        {/* PC2 Agent Link */}
        <div className="telemetry-card">
          <div className="telemetry-label">เครื่องปลายทาง (PC2)</div>
          <div className="telemetry-value">
            {pc2Online ? (
              <span className="text-success">เชื่อมต่อพร้อมรับคำสั่ง</span>
            ) : pc2Online === false ? (
              <span className="text-danger">ไม่พบการเชื่อมต่อ agent</span>
            ) : (
              <span className="text-muted">กำลังตรวจสอบสถานะ…</span>
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
          <div className="telemetry-label">เซิร์ฟเวอร์หลัก (PC1 Link)</div>
          <div className="telemetry-value">
            {wsUp ? (
              <span className="text-success flex-align">
                <WifiIcon size={15} /> WebSocket เรียลไทม์
              </span>
            ) : (
              <span className="text-warning flex-align">
                <WifiOffIcon size={15} /> กำลังเชื่อมต่อใหม่…
              </span>
            )}
          </div>
          <div className="telemetry-extra">
            <div className="extra-item">
              <span>คิวคำสั่งปัจจุบัน:</span> <strong>{activeJobsCount} งาน</strong>
            </div>
            <div className="extra-item">
              <span>ประวัติในเซสชัน:</span> <strong>{totalJobs} คำสั่ง</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Emergency Kill-Switch Callout */}
      <div className="killswitch-callout">
        <div className="callout-content">
          <div className="callout-heading">
            <StopIcon size={16} />
            <span>ระบบหยุดฉุกเฉิน (Emergency Kill-Switch)</span>
          </div>
          <p className="callout-text">
            หากคอมพิวเตอร์กำลังทำคำสั่งผิดพลาด หรือต้องการยกเลิกคำสั่งทั้งหมดทันที กดปุ่มหยุดด้านล่าง
          </p>
        </div>
        <button
          type="button"
          className="btn-killswitch"
          onClick={onEmergencyStop}
          aria-label="หยุดการทำงานฉุกเฉินทันที"
        >
          <StopIcon size={16} />
          <span>หยุดการทำงานทันที</span>
        </button>
      </div>
    </div>
  );
}
