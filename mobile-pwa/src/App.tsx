import { useCallback, useEffect, useMemo, useState } from "react";
import { Api, ApiError, type Job, type ServerEvent } from "./api";
import { isActive, upsertJob } from "./labels";
import { useRecorder } from "./useRecorder";

import { Header } from "./components/Header";
import { MicrophoneHero } from "./components/MicrophoneHero";
import { CommandInput } from "./components/CommandInput";
import { ActiveJobCard } from "./components/ActiveJobCard";
import { PCStatusPanel } from "./components/PCStatusPanel";
import { CommandHistory } from "./components/CommandHistory";
import { TokenSetup } from "./components/TokenSetup";
import { TokenModal } from "./components/TokenModal";
import { OfflineBanner } from "./components/OfflineBanner";
import { InstallPrompt } from "./components/InstallPrompt";

const TOKEN_KEY = "voicepc.token";
const THEME_KEY = "voicepc.theme";

function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

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
  const [token, setToken] = useState(readToken);
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

  if (!token) {
    return (
      <div className="app-root theme-container">
        <TokenSetup onSave={setToken} />
      </div>
    );
  }

  return (
    <Remote
      token={token}
      theme={theme}
      onToggleTheme={toggleTheme}
      onLogout={() => {
        try {
          localStorage.removeItem(TOKEN_KEY);
        } catch {
          /* ignore */
        }
        setToken("");
      }}
      onUpdateToken={(newToken) => setToken(newToken)}
    />
  );
}

interface RemoteProps {
  token: string;
  theme: "dark" | "light";
  onToggleTheme: () => void;
  onLogout: () => void;
  onUpdateToken: (t: string) => void;
}

function Remote({ token, theme, onToggleTheme, onLogout, onUpdateToken }: RemoteProps) {
  const api = useMemo(() => new Api(token), [token]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pc2Online, setPc2Online] = useState<boolean | null>(null);
  const [pc2Data, setPc2Data] = useState<Record<string, unknown> | null>(null);
  const [wsUp, setWsUp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [, tick] = useState(0);

  const handleError = useCallback(
    (e: unknown) => {
      if (e instanceof ApiError && e.status === 401) {
        try {
          localStorage.removeItem(TOKEN_KEY);
        } catch {
          /* ignore */
        }
        onLogout();
        return;
      }
      setError(e instanceof Error ? e.message : String(e));
    },
    [onLogout],
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
          return handleError(new ApiError(401, "Token rejected by server"));
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

  const submit = useCallback(
    (p: Promise<Job>) => {
      setError(null);
      p.then((job) => {
        setJobs((l) => upsertJob(l, job));
        setSelectedJob(job);
      }).catch(handleError);
    },
    [handleError],
  );

  const onAudio = useCallback((blob: Blob) => submit(api.sendAudio(blob)), [api, submit]);
  const mic = useRecorder(onAudio);

  // Active or most recent job
  const activeJob = jobs.find(isActive) || selectedJob || jobs[0];
  const busy = jobs.some(isActive);
  const activeJobsCount = jobs.filter(isActive).length;

  const handleEmergencyStop = () => {
    api
      .stop()
      .then((r) => {
        if (!r.pc2_stopped) {
          setError("หยุดฝั่ง PC1 แล้ว แต่ติดต่อ PC2 ไม่ได้ — กรุณากดปุ่ม Kill-Switch บนเครื่องด้วย");
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

      {/* Responsive Main Layout Container */}
      <main className="app-main-layout">
        {/* Left / Primary Column: Voice Hero + Active Inspector + Command Input */}
        <div className="layout-col-primary">
          {/* Active / Current Job Card */}
          {activeJob && (
            <section className="active-job-section" aria-label="สถานะคำสั่งปัจจุบัน">
              <ActiveJobCard
                job={activeJob}
                api={api}
                onError={handleError}
                onUpdate={(j) => {
                  setJobs((l) => upsertJob(l, j));
                  setSelectedJob(j);
                }}
              />
            </section>
          )}

          {/* Voice Assistant Primary Interaction Panel */}
          <section className="voice-assistant-section" aria-label="สั่งการด้วยเสียง">
            <MicrophoneHero
              mic={mic}
              wsUp={wsUp}
              pc2Online={pc2Online}
              busy={busy}
              currentJobState={activeJob?.state}
            />
          </section>

          {/* Text Command Input & Quick Actions */}
          <section className="command-input-section" aria-label="พิมพ์คำสั่ง">
            <CommandInput
              onSubmitText={(txt) => submit(api.sendText(txt))}
              busy={busy}
              error={error}
              onClearError={() => setError(null)}
            />
          </section>
        </div>

        {/* Right / Secondary Column: Telemetry + Command History */}
        <div className="layout-col-secondary">
          {/* PC System Telemetry & Remote Session */}
          <section className="telemetry-section" aria-label="สถานะเครื่องคอมพิวเตอร์">
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

      {/* Token / Settings Modal */}
      <TokenModal
        isOpen={isSettingsOpen}
        currentToken={token}
        onClose={() => setIsSettingsOpen(false)}
        onUpdateToken={onUpdateToken}
        onLogout={onLogout}
      />
    </div>
  );
}
