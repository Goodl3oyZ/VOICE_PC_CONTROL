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
            <h3 id="modal-title">Account and device</h3>
          </div>
          <button type="button" className="modal-close-btn" onClick={onClose} aria-label="Close">
            <XIcon size={18} />
          </button>
        </div>

        <div className="modal-body">
          <p className="modal-desc">Signed in with Google: {email}</p>
          <p className="modal-desc">This device is paired (verified with the Secret Key)</p>

          <hr className="modal-divider" />

          <div className="modal-logout-section">
            <div>
              <div className="logout-title">Sign out</div>
              <div className="logout-desc">Next time only Google sign-in is needed, not the Secret Key</div>
            </div>
            <button type="button" className="btn-modal-logout" onClick={() => { onClose(); onLogout(); }}>
              <LogOutIcon size={16} />
              <span>Sign out</span>
            </button>
          </div>

          <hr className="modal-divider" />

          <div className="modal-logout-section">
            <div>
              <div className="logout-title">Un-pair this device</div>
              <div className="logout-desc">Revokes this device now; the Secret Key is needed to use it again</div>
            </div>
            <button type="button" className="btn-modal-logout" onClick={() => { onClose(); onUnpair(); }}>
              <ShieldAlertIcon size={16} />
              <span>Un-pair</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
