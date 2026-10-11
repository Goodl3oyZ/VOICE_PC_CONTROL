import { KeyIcon, LogOutIcon, ShieldAlertIcon, XIcon } from "./Icons";

interface SessionModalProps {
  isOpen: boolean;
  email: string | null;
  onClose: () => void;
  onLogout: () => void;
  onUnpair: () => void;
}

/** Account + device management: sign out (device stays paired) or un-pair this device entirely. */
export function SessionModal({ isOpen, email, onClose, onLogout, onUnpair }: SessionModalProps) {
  if (!isOpen) return null;
  return (
    <div className="modal-backdrop" onClick={onClose} role="dialog" aria-modal="true" aria-labelledby="modal-title">
      <div className="modal-dialog" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <div className="modal-title-group">
            <KeyIcon size={20} />
            <h3 id="modal-title">บัญชีและอุปกรณ์</h3>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="ปิด">
            <XIcon size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">ล็อกอินด้วย Google: {email}</p>
          <p className="modal-desc">อุปกรณ์นี้ผูกกับระบบแล้ว (ยืนยันด้วย Secret Key)</p>

          <hr className="modal-divider" />

          <div className="modal-logout-section">
            <div>
              <div className="logout-title">ออกจากระบบ</div>
              <div className="logout-desc">ครั้งหน้าล็อกอิน Google อย่างเดียว ไม่ต้องใส่ Secret Key ใหม่</div>
            </div>
            <button type="button" className="btn-modal-logout" onClick={() => { onClose(); onLogout(); }}>
              <LogOutIcon size={16} />
              <span>ออกจากระบบ</span>
            </button>
          </div>

          <hr className="modal-divider" />

          <div className="modal-logout-section">
            <div>
              <div className="logout-title">ยกเลิกการผูกอุปกรณ์นี้</div>
              <div className="logout-desc">เพิกถอนสิทธิ์ของเครื่องนี้ทันที ต้องใส่ Secret Key ใหม่ถ้าจะใช้อีก</div>
            </div>
            <button type="button" className="btn-modal-logout" onClick={() => { onClose(); onUnpair(); }}>
              <ShieldAlertIcon size={16} />
              <span>ยกเลิกการผูก</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
