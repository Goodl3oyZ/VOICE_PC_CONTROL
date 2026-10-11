import { useState, type FormEvent } from "react";
import { KeyIcon, LogOutIcon, TerminalIcon, XIcon } from "./Icons";

interface TokenModalProps {
  isOpen: boolean;
  currentToken: string;
  onClose: () => void;
  onUpdateToken: (token: string) => void;
  onLogout: () => void;
}

export function TokenModal({
  isOpen,
  currentToken,
  onClose,
  onUpdateToken,
  onLogout,
}: TokenModalProps) {
  const [val, setVal] = useState(currentToken);
  const [savedSuccess, setSavedSuccess] = useState(false);

  if (!isOpen) return null;

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const clean = val.trim();
    if (!clean) return;
    try {
      localStorage.setItem("voicepc.token", clean);
    } catch {
      /* ignore */
    }
    onUpdateToken(clean);
    setSavedSuccess(true);
    setTimeout(() => {
      setSavedSuccess(false);
      onClose();
    }, 700);
  };

  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <KeyIcon size={20} />
            <h3 id="modal-title">ตั้งค่า Device Token</h3>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="ปิด">
            <XIcon size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">
            โทเค็นใช้เพื่อยืนยันตัวตนของอุปกรณ์นี้กับเซิร์ฟเวอร์ PC1 Orchestrator
          </p>

          <div className="modal-instructions">
            <div className="instr-title">
              <TerminalIcon size={14} />
              <span>สร้างโทเค็นใหม่บน PC1:</span>
            </div>
            <code>python -m app.cli add-device phone1</code>
          </div>

          <form onSubmit={handleSubmit} className="modal-form">
            <div className="form-field">
              <label htmlFor="modal-token-input">Device Token ปัจจุบัน:</label>
              <input
                id="modal-token-input"
                type="text"
                value={val}
                onChange={(e) => setVal(e.target.value)}
                placeholder="กรอก device token"
                className="modal-input"
              />
            </div>

            <div className="modal-btn-row">
              <button type="submit" className="btn-modal-save" disabled={!val.trim()}>
                {savedSuccess ? "บันทึกเรียบร้อย!" : "บันทึกการเปลี่ยนแปลง"}
              </button>
            </div>
          </form>

          <hr className="modal-divider" />

          <div className="modal-logout-section">
            <div>
              <div className="logout-title">ออกจากระบบอุปกรณ์นี้</div>
              <div className="logout-desc">ลบโทเค็นออกจากหน่วยความจำและกลับสู่หน้าตั้งค่าเริ่มต้น</div>
            </div>
            <button
              type="button"
              className="btn-modal-logout"
              onClick={() => {
                onClose();
                onLogout();
              }}
            >
              <LogOutIcon size={16} />
              <span>ออกจากระบบ</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
