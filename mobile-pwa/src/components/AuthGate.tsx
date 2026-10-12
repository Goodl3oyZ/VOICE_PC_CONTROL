import { useState, type FormEvent } from "react";
import { ApiError, type Api, type AuthState } from "../api";
import { KeyIcon, LaptopIcon, ShieldAlertIcon } from "./Icons";

const AUTH_ERRORS: Record<string, string> = {
  not_allowed: "This Google account is not allowed to use this app",
  state: "The sign-in expired or was invalid, please try again",
  denied: "Google sign-in was cancelled",
};

function authErrorFromUrl(): string | null {
  const code = new URLSearchParams(window.location.search).get("auth_error");
  if (!code) return null;
  window.history.replaceState(null, "", window.location.pathname);
  return AUTH_ERRORS[code] ?? "Sign-in failed, please try again";
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
          <p className="setup-subtitle">Control your computer remotely with voice commands and local AI</p>
        </div>

        <div className="setup-instruction-box">
          <div className="instruction-heading">
            <ShieldAlertIcon size={16} />
            <span>Two-step sign-in</span>
          </div>
          <p>1) Sign in with an allowed Google account</p>
          <p className="instruction-foot">2) Enter the Secret Key once to pair this device (not needed again)</p>
        </div>


        {error && <div className="setup-error-msg">{error}</div>}

        {auth.google_enabled ? (
          <a className="btn-setup-submit" href="/auth/google/login">
            <span>Sign in with Google</span>
          </a>
        ) : (
          <div className="setup-error-msg">Google sign-in is not configured on the server</div>
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
        if (err instanceof ApiError && err.status === 403) setError("Wrong Secret Key");
        else if (err instanceof ApiError && err.status === 429) setError("Too many wrong attempts, please wait 15 minutes");
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
          <h1>Pair this device</h1>
          <p className="setup-subtitle">Signed in as {auth.email}</p>
        </div>

        <div className="setup-instruction-box">
          <div className="instruction-heading">
            <KeyIcon size={16} />
            <span>Where is the Secret Key?</span>
          </div>
          <p>Create or rotate it on the PC1 server with:</p>
          <pre className="code-block">
            <code>vpc-cli set-pairing-key</code>
          </pre>
          <p className="instruction-foot">Needed once per device. A lost device can be un-paired at any time.</p>
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
              <span>Device name</span>
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
            <span>{busy ? "Checking…" : "Pair device and start"}</span>
          </button>
        </form>

        <button type="button" className="btn-modal-logout" style={{ marginTop: 16 }} onClick={onSignOut}>
          <span>Use another Google account</span>
        </button>
      </div>
    </div>
  );
}
