import { useState, type FormEvent } from "react";
import { ApiError, type Api, type AuthState } from "../api";
import { KeyIcon, LaptopIcon, ShieldAlertIcon } from "./Icons";

const AUTH_ERRORS: Record<string, string> = {
  not_allowed: "บัญชี Google นี้ไม่ได้รับอนุญาตให้ใช้งานระบบ",
  state: "การล็อกอินหมดอายุหรือไม่ถูกต้อง กรุณาลองใหม่",
  denied: "ยกเลิกการล็อกอินกับ Google แล้ว",
};

function authErrorFromUrl(): string | null {
  const code = new URLSearchParams(window.location.search).get("auth_error");
  if (!code) return null;
  window.history.replaceState(null, "", window.location.pathname);
  return AUTH_ERRORS[code] ?? "ล็อกอินไม่สำเร็จ กรุณาลองใหม่";
}

function guessDeviceLabel(): string {
  const ua = navigator.userAgent;
  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  if (/Android/i.test(ua)) return "Android";
  if (/Windows/i.test(ua)) return "Windows";
  if (/Mac/i.test(ua)) return "Mac";
  return "device";
}

/** Step 1: Google sign-in (only allow-listed emails get a session). */
export function LoginScreen({ auth }: { auth: AuthState }) {
  const [error] = useState(authErrorFromUrl);
  return (
    <div className="setup-container">
      <div className="setup-card">
        <div className="setup-header">
          <div className="setup-logo-badge">
            <LaptopIcon size={32} />
          </div>
          <h1>Voice PC Remote</h1>
          <p className="setup-subtitle">ระบบควบคุมคอมพิวเตอร์ระยะไกลด้วยคำสั่งเสียง AI</p>
        </div>

        <div className="setup-instruction-box">
          <div className="instruction-heading">
            <ShieldAlertIcon size={16} />
            <span>ยืนยันตัวตน 2 ขั้น</span>
          </div>
          <p>1) ล็อกอินด้วยบัญชี Google ที่ได้รับอนุญาต</p>
          <p className="instruction-foot">2) ใส่ Secret Key ครั้งแรกเพื่อผูกอุปกรณ์นี้ (ครั้งต่อไปไม่ต้องใส่อีก)</p>
        </div>

        {error && <div className="setup-error-msg">{error}</div>}

        {auth.google_enabled ? (
          <a className="btn-setup-submit" href="/auth/google/login">
            <span>เข้าสู่ระบบด้วย Google</span>
          </a>
        ) : (
          <div className="setup-error-msg">ยังไม่ได้ตั้งค่า Google OAuth บนเซิร์ฟเวอร์</div>
        )}
      </div>
    </div>
  );
}

/** Step 2: one-time Secret Key to pair this browser; the server answers with an HttpOnly device cookie. */
export function PairScreen({ api, auth, onPaired, onSignOut }: {
  api: Api;
  auth: AuthState;
  onPaired: () => void;
  onSignOut: () => void;
}) {
  const [key, setKey] = useState("");
  const [label, setLabel] = useState(guessDeviceLabel);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!key.trim() || busy) return;
    setBusy(true);
    setError(null);
    api
      .pair(key.trim(), label.trim() || "device")
      .then(onPaired)
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 403) setError("Secret Key ไม่ถูกต้อง");
        else if (err instanceof ApiError && err.status === 429) setError("ใส่ผิดหลายครั้งเกินไป กรุณารอ 15 นาที");
        else setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => setBusy(false));
  };

  return (
    <div className="setup-container">
      <div className="setup-card">
        <div className="setup-header">
          <div className="setup-logo-badge">
            <KeyIcon size={32} />
          </div>
          <h1>ผูกอุปกรณ์นี้</h1>
          <p className="setup-subtitle">ล็อกอินแล้วในชื่อ {auth.email}</p>
        </div>

        <div className="setup-instruction-box">
          <div className="instruction-heading">
            <KeyIcon size={16} />
            <span>Secret Key อยู่ที่ไหน?</span>
          </div>
          <p>สร้างหรือเปลี่ยน key บนเซิร์ฟเวอร์ PC1 ด้วยคำสั่ง:</p>
          <pre className="code-block">
            <code>vpc-cli set-pairing-key</code>
          </pre>
          <p className="instruction-foot">ใส่ครั้งเดียวต่ออุปกรณ์ ถ้าเครื่องหายสามารถยกเลิกการผูกได้</p>
        </div>

        <form className="setup-form" onSubmit={submit}>
          <div className="form-field">
            <label htmlFor="pair-key" className="form-label">
              <KeyIcon size={16} />
              <span>Secret Key</span>
            </label>
            <input
              id="pair-key"
              type="password"
              className="setup-token-input"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="XXXX-XXXX-XXXX-XXXX-XXXX"
              autoFocus
              autoComplete="off"
              spellCheck={false}
            />
          </div>
          <div className="form-field">
            <label htmlFor="pair-label" className="form-label">
              <LaptopIcon size={16} />
              <span>ชื่ออุปกรณ์</span>
            </label>
            <input
              id="pair-label"
              type="text"
              className="setup-token-input"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              maxLength={40}
            />
          </div>

          {error && <div className="setup-error-msg">{error}</div>}

          <button type="submit" className="btn-setup-submit" disabled={!key.trim() || busy}>
            <span>{busy ? "กำลังตรวจสอบ…" : "ผูกอุปกรณ์และเริ่มใช้งาน"}</span>
          </button>
        </form>

        <button type="button" className="btn-modal-logout" style={{ marginTop: 16 }} onClick={onSignOut}>
          <span>ใช้บัญชี Google อื่น</span>
        </button>
      </div>
    </div>
  );
}
