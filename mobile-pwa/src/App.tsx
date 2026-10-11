import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Api, ApiError, type AuthState, type Job, type ServerEvent } from "./api";
import { isActive, upsertJob } from "./labels";
import { useRecorder } from "./useRecorder";
import { useHandsFree } from "./useHandsFree";
import { isSpeaking, speak, utteranceFor } from "./speech";

import { Header } from "./components/Header";
import { MicrophoneHero } from "./components/MicrophoneHero";
import { CommandInput } from "./components/CommandInput";
import { ActiveJobCard } from "./components/ActiveJobCard";
import { PCStatusPanel } from "./components/PCStatusPanel";
import { CommandHistory } from "./components/CommandHistory";
import { LoginScreen, PairScreen } from "./components/AuthGate";
import { SessionModal } from "./components/SessionModal";
import { CommandGuide } from "./components/CommandGuide";
import { OfflineBanner } from "./components/OfflineBanner";
import { InstallPrompt } from "./components/InstallPrompt";
import { EnglishOnlyNotice } from "./components/EnglishOnlyNotice";
import { HandsFreePanel } from "./components/HandsFreePanel";

const THEME_KEY = "voicepc.theme";

function readTheme(): "dark" | "light" {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  } catch {
    return "dark";
  }
}

export default function App() {
  const api = useMemo(() => new Api(), []);
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [authError, setAuthError] = useState<string | null>(null);
  const [theme, setTheme] = useState<"dark" | "light">(readTheme);

  // Synchronize data-theme on document root
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
  }, [theme]);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => (prev === "dark" ? "light" : "dark"));
  }, []);

  const refreshAuth = useCallback(() => {
    api
      .me()
      .then((a) => {
        setAuth(a);
        setAuthError(null);
      })
      .catch((e: unknown) => setAuthError(e instanceof Error ? e.message : String(e)));
  }, [api]);

  useEffect(refreshAuth, [refreshAuth]);

  const logout = useCallback(() => {
    api.logout().finally(refreshAuth);
  }, [api, refreshAuth]);

  const unpair = useCallback(() => {
    api.unpair().finally(refreshAuth);
  }, [api, refreshAuth]);

  if (!auth) {
    return (
      <div className="app-root theme-container">
        <div className="setup-container">
          <div className="setup-card">
            <p className="setup-subtitle">{authError ? `Cannot reach the server: ${authError}` : "Checking your sign-in…"}</p>
            {authError && (
              <button type="button" className="btn-setup-submit" onClick={refreshAuth}>
                <span>Try again</span>
              </button>
            )}
          </div>
        </div>
      </div>
    );
  }

  if (!auth.authenticated) {
    return (
      <div className="app-root theme-container">
        <LoginScreen auth={auth} />
      </div>
    );
  }

  if (!auth.paired) {
    return (
      <div className="app-root theme-container">
        <PairScreen api={api} auth={auth} onPaired={refreshAuth} onSignOut={logout} />
      </div>
    );
  }

  return (
    <Remote
      api={api}
      email={auth.email}
      theme={theme}
      onToggleTheme={toggleTheme}
      onSessionLost={refreshAuth}
      onLogout={logout}
      onUnpair={unpair}
    />
  );
}
interface RemoteProps {
  api: Api;
  email: string | null;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onSessionLost: () => void;
  onLogout: () => void;
  onUnpair: () => void;
}

function Remote({ api, email, theme, onToggleTheme, onSessionLost, onLogout, onUnpair }: RemoteProps) {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pc2Online, setPc2Online] = useState<boolean | null>(null);
  const [pc2Data, setPc2Data] = useState<Record<string, unknown> | null>(null);
  const [wsUp, setWsUp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [isGuideOpen, setIsGuideOpen] = useState(false);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [, tick] = useState(0);

  const handleError = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        onSessionLost(); // session expired or device revoked: back to Google / Secret Key screens
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    },
    [onSessionLost],
  );

  const refresh = useCallback(() => {
    api.jobs().then(setJobs).catch(handleError);
    api
      .status()
      .then((s) => {
        setPc2Online(s.pc2_online);
        setPc2Data(s.pc2);
      })
      .catch(() => {});
  }, [api, handleError]);

  // WebSocket with exponential backoff reconnect and full state resync
  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      ws = new WebSocket(api.eventsUrl());
      ws.onopen = () => {
        retry = 0;
        setWsUp(true);
        refresh();
      };
      ws.onmessage = (m) => {
        try {
          const ev = JSON.parse(m.data) as ServerEvent;
          if (ev.type === "job.update") {
            setJobs((list) => upsertJob(list, ev.job));
          } else if (ev.type === "pc2.status") {
            setPc2Online(ev.online);
            if (ev.status) setPc2Data(ev.status);
          }
        } catch {
          /* non-JSON packet */
        }
      };
      ws.onclose = (e) => {
        setWsUp(false);
        if (closed) return;
        if (e.code === 4401) {
          return handleError(new ApiError(401, "Session rejected by server"));
        }
        timer = window.setTimeout(connect, Math.min(10_000, 500 * 2 ** retry++));
      };
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, [api, refresh, handleError]);

  // 1-second interval timer for countdowns and relative timing displays
  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  // Jobs started from this device: their results may be spoken aloud (Phase 4)
  const myJobs = useRef(new Set<string>());
  const spoken = useRef(new Map<string, string>());
  const [speakOn, setSpeakOn] = useState(() => {
    try {
      return localStorage.getItem("vpc.speak") === "1";
    } catch {
      return false;
    }
  });
  const toggleSpeak = useCallback(() => {
    setSpeakOn((v) => {
      try {
        localStorage.setItem("vpc.speak", v ? "0" : "1");
      } catch {
        /* per-device preference only */
      }
      if (v) window.speechSynthesis?.cancel();
      return !v;
    });
  }, []);

  const track = useCallback((job: Job) => {
    myJobs.current.add(job.id);
    setJobs((l) => upsertJob(l, job));
    setSelectedJob(job);
  }, []);

  const submit = useCallback(
    (p: Promise<Job>) => {
      setError(null);
      p.then(track).catch(handleError);
    },
    [handleError, track],
  );

  const onAudio = useCallback((blob: Blob) => submit(api.sendAudio(blob)), [api, submit]);
  const mic = useRecorder(onAudio);
  const micRecording = useRef(false);
  micRecording.current = mic.state === "recording";
  const handsFree = useHandsFree(
    useCallback((wav: Blob, armed: boolean) => api.sendWake(wav, armed), [api]),
    track,
    useCallback(() => isSpeaking() || micRecording.current, []),
  );

  useEffect(() => {
    if (!speakOn) return;
    for (const j of jobs) {
      if (!myJobs.current.has(j.id) || spoken.current.get(j.id) === j.state) continue;
      const text = utteranceFor(j);
      if (text === null) continue;
      spoken.current.set(j.id, j.state);
      speak(text);
    }
  }, [jobs, speakOn]);

  // Active or most recent job
  const activeJob = jobs.find(isActive) || selectedJob || jobs[0];
  const busy = jobs.some(isActive);
  const activeJobsCount = jobs.filter(isActive).length;

  const handleEmergencyStop = () => {
    api
      .stop()
      .then((r) => {
        if (!r.pc2_stopped) {
          setError("Stopped on PC1, but PC2 could not be reached — use the kill switch on the PC as well");
        } else {
          setError(null);
        }
        refresh();
      })
      .catch(handleError);
  };

  return (
    <div className="app-shell">
      {/* Offline Banner */}
      <OfflineBanner />

      {/* Main App Header */}
      <Header
        pc2Online={pc2Online}
        wsUp={wsUp}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onOpenSettings={() => setIsSettingsOpen(true)}
        onEmergencyStop={handleEmergencyStop}
      />

      {/* PWA Install Promotion Banner */}
      <InstallPrompt />

      {/* Voice/text commands are accepted in English only */}
      <EnglishOnlyNotice />

      {/* Responsive Main Layout Container */}
      <main className="app-main-layout">
        {/* Left / Primary Column: Voice Hero + Active Inspector + Command Input */}
        <div className="layout-col-primary">
          {/* Active / Current Job Card */}
          {activeJob && (
            <section className="active-job-section" aria-label="Current command">
              <ActiveJobCard
                job={activeJob}
                api={api}
                onError={handleError}
                onUpdate={(j) => {
                  setJobs((l) => upsertJob(l, j));
                  setSelectedJob(j);
                }}
                onNewJob={submit}
              />
            </section>
          )}

          {/* Voice Assistant Primary Interaction Panel */}
          <section className="voice-assistant-section" aria-label="Voice command">
            <MicrophoneHero
              mic={mic}
              wsUp={wsUp}
              pc2Online={pc2Online}
              busy={busy}
              currentJobState={activeJob?.state}
            />
            <HandsFreePanel
              state={handsFree.state}
              error={handsFree.error}
              on={handsFree.on}
              onToggle={() => {
                if (!handsFree.on && !speakOn) toggleSpeak(); // hands-free is pointless without spoken replies
                handsFree.toggle();
              }}
              speakOn={speakOn}
              onToggleSpeak={toggleSpeak}
            />
          </section>

          {/* Text Command Input & Quick Actions */}
          <section className="command-input-section" aria-label="Type a command">
            <CommandInput
              onSubmitText={(txt) => submit(api.sendText(txt))}
              busy={busy}
              error={error}
              onClearError={() => setError(null)}
              onOpenGuide={() => setIsGuideOpen(true)}
            />
          </section>
        </div>

        {/* Right / Secondary Column: Telemetry + Command History */}
        <div className="layout-col-secondary">
          {/* PC System Telemetry & Remote Session */}
          <section className="telemetry-section" aria-label="Computer status">
            <PCStatusPanel
              pc2Online={pc2Online}
              pc2Data={pc2Data}
              wsUp={wsUp}
              totalJobs={jobs.length}
              activeJobsCount={activeJobsCount}
              onEmergencyStop={handleEmergencyStop}
            />
          </section>

          {/* Command History Feed */}
          <section className="history-section-wrapper">
            <CommandHistory
              jobs={jobs}
              onSelectJob={(j) => setSelectedJob(j)}
            />
          </section>
        </div>
      </main>

      {/* "What can I say?" guide (from GET /capabilities) */}
      <CommandGuide
        isOpen={isGuideOpen}
        api={api}
        onClose={() => setIsGuideOpen(false)}
        onRun={(cmd) => submit(api.sendText(cmd))}
      />

      {/* Account / Device Modal */}
      <SessionModal
        isOpen={isSettingsOpen}
        email={email}
        onClose={() => setIsSettingsOpen(false)}
        onLogout={onLogout}
        onUnpair={onUnpair}
      />
    </div>
  );
}
