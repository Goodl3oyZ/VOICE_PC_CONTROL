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
import { AppsTab } from "./components/AppsTab";
import { BottomNav, type NavTab } from "./components/BottomNav";
import type { OrbState } from "./components/AIOrb";


const THEME_KEY = "voicepc.theme.v2";

function readTheme(): "dark" | "light" {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "light" || saved === "dark") return saved;
    return "dark";
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
              <div style={{ display: "flex", flexDirection: "column", gap: "10px", marginTop: "16px" }}>
                <button type="button" className="btn-setup-submit" onClick={refreshAuth}>
                  <span>Try again</span>
                </button>
              </div>
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

  const [navTab, setNavTab] = useState<NavTab>("home");
  const [openFlow, setOpenFlow] = useState<string | null>(null);
  const flowOpened = useRef(new Set<string>());

  // "YouTube" / "open Cursor" said on this phone: PC1 answers with a flow job -> open that wizard
  useEffect(() => {
    for (const j of jobs) {
      if (j.planner !== "flow" || !j.flow || j.state !== "done" || !myJobs.current.has(j.id)) continue;
      if (flowOpened.current.has(j.id)) continue;
      flowOpened.current.add(j.id);
      setOpenFlow(j.flow);
      setNavTab("apps");
    }
  }, [jobs]);
  const onFlowOpened = useCallback(() => setOpenFlow(null), []);
  const [flash, setFlash] = useState<"success" | "error" | null>(null);
  const prevJobStates = useRef<Map<string, string>>(new Map());

  // Flash the orb briefly when a job finishes (done -> success, failed -> error), then back to idle.
  useEffect(() => {
    let next: "success" | "error" | null = null;
    for (const j of jobs) {
      const prev = prevJobStates.current.get(j.id);
      if (prev && prev !== j.state) {
        if (j.state === "done") next = "success";
        else if (j.state === "failed") next = "error";
      }
      prevJobStates.current.set(j.id, j.state);
    }
    if (!next) return;
    setFlash(next);
    const timer = window.setTimeout(() => setFlash(null), 2500);
    return () => window.clearTimeout(timer);
  }, [jobs]);

  // Derive Orb state strictly from active system and job state
  const orbState = useMemo<OrbState>(() => {
    if (!wsUp || pc2Online === false) return "offline";
    if (mic.state === "denied" || mic.state === "insecure") return "error";
    if (mic.state === "recording") return "listening";
    if (handsFree.state === "hearing" || handsFree.state === "armed") return "listening";
    if (flash) return flash;
    if (activeJob?.state === "transcribing" || activeJob?.state === "planning" || activeJob?.state === "routing") {
      return "processing";
    }
    if (
      activeJob?.state === "created" ||
      activeJob?.state === "dispatching" ||
      activeJob?.state === "running" ||
      activeJob?.state === "verifying"
    ) {
      return "executing";
    }
    return "idle";
  }, [wsUp, pc2Online, mic.state, handsFree.state, flash, activeJob?.state]);

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
    <div className="app-shell has-bottom-nav">
      {/* Offline Banner */}
      <OfflineBanner />

      {/* Main App Header */}
      <Header
        pc2Online={pc2Online}
        wsUp={wsUp}
        theme={theme}
        onToggleTheme={onToggleTheme}
        onOpenSettings={() => setNavTab("settings")}
        onEmergencyStop={handleEmergencyStop}
      />

      {/* PWA Install Promotion Banner */}
      <InstallPrompt />

      {/* Voice/text commands are accepted in English only */}
      <EnglishOnlyNotice />

      {/* Tabbed Content View */}
      <main className="app-main-layout">
        {navTab === "home" && (
          <div className="tab-pane tab-home animate-fade-in">
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

            {/* AI Assistant Centerpiece Hero */}
            <section className="voice-assistant-section" aria-label="Voice command">
              <MicrophoneHero
                mic={mic}
                wsUp={wsUp}
                pc2Online={pc2Online}
                currentJobState={activeJob?.state}
                currentJobText={activeJob?.text || null}
                orbState={orbState}
                handsFree={handsFree}
                micMode={handsFree.on ? "handsfree" : mic.mode}
                onMicMode={(m) => {
                  if (m === "handsfree") {
                    if (!handsFree.on) {
                      if (!speakOn) toggleSpeak(); // hands-free is pointless without spoken replies
                      handsFree.toggle();
                    }
                    return;
                  }
                  if (handsFree.on) handsFree.toggle();
                  mic.setMode(m);
                }}
                speakOn={speakOn}
                onToggleSpeak={toggleSpeak}
                onExecuteCommand={(cmd) => submit(api.sendText(cmd))}
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
        )}

        {navTab === "apps" && (
          <div className="tab-pane tab-apps animate-fade-in">
            <AppsTab
              api={api}
              jobs={jobs}
              openFlow={openFlow}
              onOpened={onFlowOpened}
              onJob={track}
              onUpdate={(j) => setJobs((l) => upsertJob(l, j))}
              onError={handleError}
            />
          </div>
        )}

        {navTab === "activity" && (
          <div className="tab-pane tab-activity animate-fade-in">
            {/* Command History Feed */}
            <section className="history-section-wrapper">
              <CommandHistory
                jobs={jobs}
                onSelectJob={(j) => {
                  setSelectedJob(j);
                  setNavTab("home");
                }}
              />
            </section>

          </div>
        )}

        {navTab === "settings" && (
          <div className="tab-pane tab-settings animate-fade-in">
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

            {/* Account & Session Controls Card */}
            <section className="settings-card-section" aria-label="Account and session settings">
              <div className="settings-panel">
                <div className="settings-panel-header">
                  <h3>Device & Account</h3>
                </div>
                <div className="settings-panel-body">
                  <div className="settings-row">
                    <span className="settings-label">Account</span>
                    <span className="settings-value">{email || "Secret Key Paired"}</span>
                  </div>
                  <div className="settings-actions-group">
                    <button
                      type="button"
                      className="btn-settings-action"
                      onClick={() => setIsGuideOpen(true)}
                    >
                      Command Capabilities Guide
                    </button>
                    {/* Same-origin GET: the HttpOnly session/device cookies authenticate the download. */}
                    <a className="btn-settings-action" href="/audit/export?format=csv&days=30" download>
                      Download audit log (30 days, CSV)
                    </a>
                    <button
                      type="button"
                      className="btn-settings-action"
                      onClick={onUnpair}
                    >
                      Unpair Device
                    </button>
                    <button
                      type="button"
                      className="btn-settings-action btn-danger"
                      onClick={onLogout}
                    >
                      Sign Out
                    </button>
                  </div>
                </div>
              </div>
            </section>
          </div>
        )}
      </main>

      {/* Bottom Navigation Bar */}
      <BottomNav
        active={navTab}
        onChange={setNavTab}
        activityCount={activeJobsCount}
      />

      {/* "What can I say?" guide (from GET /capabilities) */}
      <CommandGuide
        isOpen={isGuideOpen}
        api={api}
        onClose={() => setIsGuideOpen(false)}
        onRun={(cmd) => {
          submit(api.sendText(cmd));
          setNavTab("home");
        }}
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

