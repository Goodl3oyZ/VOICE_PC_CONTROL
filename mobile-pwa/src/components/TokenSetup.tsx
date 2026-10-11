import { useState, type FormEvent } from "react";
import { KeyIcon, LaptopIcon, TerminalIcon } from "./Icons";

interface TokenSetupProps {
  onSave: (token: string) => void;
}

export function TokenSetup({ onSave }: TokenSetupProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    const clean = value.trim();
    if (!clean) {
      setError("กรุณากรอก Device Token ก่อนดำเนินการต่อ");
      return;
    }
    try {
      localStorage.setItem("voicepc.token", clean);
    } catch {
      /* private mode: keep in memory */
    }
    onSave(clean);
  };

  return (
    <div className="setup-container">
      <div className="setup-card">
        {/* App Logo */}
        <div className="setup-header">
          <div className="setup-logo-badge">
            <LaptopIcon size={32} />
          </div>
          <h1>Voice PC Remote</h1>
          <p className="setup-subtitle">ระบบควบคุมคอมพิวเตอร์ระยะไกลด้วยคำสั่งเสียง AI</p>
        </div>

        {/* Instructions */}
        <div className="setup-instruction-box">
          <div className="instruction-heading">
            <TerminalIcon size={16} />
            <span>วิธีรับ Device Token จาก PC1</span>
          </div>
          <p>เปิด Terminal บนเครื่องคอมพิวเตอร์ PC1 แล้วรันคำสั่ง:</p>
          <pre className="code-block">
            <code>python -m app.cli add-device phone1</code>
          </pre>
          <p className="instruction-foot">จากนั้นคัดลอกโทเค็นที่ได้มาวางในช่องด้านล่าง</p>
        </div>

        {/* Input Form */}
        <form className="setup-form" onSubmit={handleSubmit}>
          <div className="form-field">
            <label htmlFor="token-input" className="form-label">
              <KeyIcon size={16} />
              <span>Device Token</span>
            </label>
            <input
              id="token-input"
              type="text"
              className="setup-token-input"
              value={value}
              onChange={(e) => {
                setValue(e.target.value);
                if (error) setError(null);
              }}
              placeholder="วางโทเค็นอุปกรณ์ที่นี่ เช่น dev_sec_..."
              autoFocus
              autoComplete="off"
              spellCheck={false}
            />
          </div>

          {error && <div className="setup-error-msg">{error}</div>}

          <button type="submit" className="btn-setup-submit" disabled={!value.trim()}>
            <span>เชื่อมต่อกับเครื่องคอมพิวเตอร์</span>
          </button>
        </form>
      </div>
    </div>
  );
}
