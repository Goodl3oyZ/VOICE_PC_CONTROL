import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Api, ApiError, type Job, type ServerEvent } from "./api";
import { STATE_TH, describeCall, isActive, riskLabel, secondsLeft, upsertJob } from "./labels";
import { useRecorder } from "./useRecorder";

const TOKEN_KEY = "voicepc.token";

function readToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export default function App() {
  const [token, setToken] = useState(readToken);
  if (!token) return <TokenSetup onSave={setToken} />;
  return <Remote token={token} onLogout={() => setToken("")} />;
}

function TokenSetup({ onSave }: { onSave: (t: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <main className="setup">
      <h1>Voice PC Remote</h1>
      <p>วาง token ของอุปกรณ์นี้ (สร้างบน PC1 ด้วย <code>python -m app.cli add-device phone1</code>)</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          const t = value.trim();
          if (!t) return;
          try {
            localStorage.setItem(TOKEN_KEY, t);
          } catch {
            /* private mode: keep in memory only */
          }
          onSave(t);
        }}
      >
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="device token" autoFocus />
        <button type="submit">บันทึก</button>
      </form>
    </main>
  );
}

function Remote({ token, onLogout }: { token: string; onLogout: () => void }) {
  const api = useMemo(() => new Api(token), [token]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [pc2Online, setPc2Online] = useState<boolean | null>(null);
  const [wsUp, setWsUp] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [text, setText] = useState("");
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
    api.status().then((s) => setPc2Online(s.pc2_online)).catch(() => {});
  }, [api, handleError]);

  // WebSocket with reconnect + resync (§14.2 step 12: "WebSocket drops -> reconnect + fetch latest").
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
        const ev = JSON.parse(m.data) as ServerEvent;
        if (ev.type === "job.update") setJobs((list) => upsertJob(list, ev.job));
        else if (ev.type === "pc2.status") setPc2Online(ev.online);
      };
      ws.onclose = (e) => {
        setWsUp(false);
        if (closed) return;
        if (e.code === 4401) return handleError(new ApiError(401, "token rejected"));
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

  useEffect(() => {
    const t = window.setInterval(() => tick((n) => n + 1), 1000);
    return () => window.clearInterval(t);
  }, []);

  const submit = useCallback(
    (p: Promise<Job>) => {
      setError(null);
      p.then((job) => setJobs((l) => upsertJob(l, job))).catch(handleError);
    },
    [handleError],
  );

  const onAudio = useCallback((blob: Blob) => submit(api.sendAudio(blob)), [api, submit]);
  const mic = useRecorder(onAudio);
  const current = jobs[0];
  const busy = jobs.some(isActive);

  const stop = () => {
    api
      .stop()
      .then((r) => setError(r.pc2_stopped ? null : "หยุดฝั่ง PC1 แล้ว แต่ติดต่อ PC2 ไม่ได้ — กด kill switch ที่เครื่องด้วย"))
      .catch(handleError);
  };

  return (
    <main className="remote">
      <header>
        <span className={`dot ${pc2Online ? "on" : pc2Online === false ? "off" : ""}`} />
        <span>PC2 {pc2Online ? "ออนไลน์" : pc2Online === false ? "ออฟไลน์" : "…"}</span>
        {!wsUp && <span className="warn">กำลังเชื่อมต่อใหม่…</span>}
        <button className="link" onClick={onLogout}>
          เปลี่ยน token
        </button>
      </header>

      <button className="stop" onClick={stop} aria-label="หยุดทันที">
        ■ หยุด
      </button>

      {current && <JobCard job={current} api={api} onError={handleError} onUpdate={(j) => setJobs((l) => upsertJob(l, j))} />}

      <section className="talk">
        <button
          className={`mic ${mic.state === "recording" ? "rec" : ""}`}
          disabled={mic.state === "insecure" || mic.state === "unsupported"}
          onPointerDown={(e) => {
            e.preventDefault();
            void mic.start();
          }}
          onPointerUp={mic.stop}
          onPointerLeave={mic.stop}
          onPointerCancel={mic.stop}
          onContextMenu={(e) => e.preventDefault()}
        >
          {mic.state === "recording" ? "ปล่อยเพื่อส่ง" : "กดค้างเพื่อพูด"}
        </button>
        {mic.state === "denied" && (
          <p className="hint">ไม่ได้รับสิทธิ์ไมโครโฟน: เปิดสิทธิ์ในตั้งค่าเบราว์เซอร์ (ไอคอนรูปกุญแจ › Microphone › Allow) หรือพิมพ์คำสั่งด้านล่างแทน</p>
        )}
        {mic.state === "insecure" && <p className="hint">ไมโครโฟนใช้ได้เฉพาะผ่าน HTTPS — เปิดผ่านที่อยู่ https:// ของ PC1</p>}
        {mic.state === "unsupported" && <p className="hint">เบราว์เซอร์นี้บันทึกเสียงไม่ได้ ใช้การพิมพ์แทน</p>}
        <form
          className="type"
          onSubmit={(e) => {
            e.preventDefault();
            if (!text.trim()) return;
            submit(api.sendText(text.trim()));
            setText("");
          }}
        >
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="หรือพิมพ์คำสั่ง เช่น เปิดโครม" maxLength={1000} />
          <button type="submit" disabled={!text.trim()}>
            ส่ง
          </button>
        </form>
        {busy && <p className="hint">มีงานกำลังทำอยู่ — คำสั่งใหม่จะต่อคิว</p>}
        {error && <p className="error">{error}</p>}
      </section>

      <section className="history">
        <h2>ประวัติ</h2>
        <ul>
          {jobs.map((j) => (
            <li key={j.id} className={j.state}>
              <div className="row">
                <span className="when">{new Date(j.created_at * 1000).toLocaleTimeString("th-TH")}</span>
                <span className="state">{STATE_TH[j.state]}</span>
              </div>
              <div className="said">{j.text || "(เสียง)"}</div>
              {j.steps[0] && <div className="tool">{j.steps.map((s) => s.tool).join(" → ")}</div>}
              {j.summary && <div className="summary">{j.summary}</div>}
            </li>
          ))}
        </ul>
      </section>
    </main>
  );
}

function JobCard({ job, api, onError, onUpdate }: { job: Job; api: Api; onError: (e: unknown) => void; onUpdate: (j: Job) => void }) {
  const [answer, setAnswer] = useState("");
  const sent = useRef(false);
  useEffect(() => {
    sent.current = false;
  }, [job.id, job.state]);

  const act = (p: Promise<Job>) => {
    if (sent.current) return;
    sent.current = true;
    p.then(onUpdate).catch((e) => {
      sent.current = false;
      onError(e);
    });
  };

  return (
    <section className={`card ${job.state}`}>
      <div className="state">{STATE_TH[job.state]}</div>
      {job.text && <div className="said">“{job.text}”</div>}

      {job.state === "clarifying" && job.question && (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (answer.trim()) act(api.reply(job.id, answer.trim()));
          }}
        >
          <p className="question">{job.question}</p>
          <input value={answer} onChange={(e) => setAnswer(e.target.value)} placeholder="ตอบที่นี่" autoFocus maxLength={1000} />
          <button type="submit">ตอบ</button>
        </form>
      )}

      {job.state === "awaiting_confirm" && job.pending && (
        <div className="confirm">
          <p>
            ต้องยืนยันก่อนทำ ({riskLabel(job.pending.risk)}) · เหลือ {secondsLeft(job.pending.expires_at)} วินาที
          </p>
          <ul>
            {describeCall(job.pending.tool, job.pending.arguments).map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
          <div className="buttons">
            <button className="approve" onClick={() => act(api.confirm(job.id, true, job.pending!.args_hash))}>
              อนุมัติ
            </button>
            <button className="reject" onClick={() => act(api.confirm(job.id, false, job.pending!.args_hash))}>
              ยกเลิก
            </button>
          </div>
        </div>
      )}

      {job.summary && job.state !== "clarifying" && <p className="summary">{job.summary}</p>}
      {job.timings_ms.total !== undefined && <p className="timing">{(job.timings_ms.total / 1000).toFixed(1)} วินาที</p>}
    </section>
  );
}
