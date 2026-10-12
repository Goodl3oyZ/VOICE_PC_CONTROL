import { useCallback, useEffect, useMemo, useState, type ComponentType } from "react";
import type { Api, FlowDef, FlowStage, Job } from "../api";
import { clearFrom, matchChoice, nextStage, resultsOf, startAnswers, stepInfo, type Answers } from "../flows";
import { useRecorder } from "../useRecorder";
import { ActiveJobCard } from "./ActiveJobCard";
import {
  ChevronLeftIcon,
  ChevronRightIcon,
  GridIcon,
  MediaIcon,
  MicIcon,
  MonitorIcon,
  PlayPauseIcon,
  SearchIcon,
  SendIcon,
  TerminalIcon,
  XIcon,
} from "./Icons";

const ICONS: Record<string, ComponentType<{ size?: number }>> = {
  youtube: PlayPauseIcon, music: MediaIcon, search: SearchIcon, code: TerminalIcon, apps: GridIcon,
  monitor: MonitorIcon,
};

function TileIcon({ flow }: { flow: FlowDef }) {
  const Icon = ICONS[flow.icon];
  return (
    <span className={`app-tile-icon tile-${flow.icon}`} aria-hidden="true">
      {Icon ? <Icon size={22} /> : <span className="app-tile-letter">{flow.title.slice(0, 1)}</span>}
    </span>
  );
}

interface AppsTabProps {
  api: Api;
  jobs: Job[];
  openFlow: string | null; // set when the user said "open YouTube"
  onOpened: () => void;
  onJob: (job: Job) => void;
  onUpdate: (job: Job) => void;
  onError: (e: unknown) => void;
  chromeConnected?: boolean | null; // from PC2 status: is the Voice PC extension connected?
}

const CHROME_FLOWS = new Set(["youtube", "music", "search"]);

function ChromeHint() {
  return (
    <p className="apps-notice" role="status">
      Chrome on the PC isn't connected, so YouTube and search won't work yet. Open Chrome on the PC and check that
      the Voice PC extension is on.
    </p>
  );
}

/** Apps tab: tiles grouped by kind; a tile opens its guided flow (redesign step 1). */
export function AppsTab({ api, jobs, openFlow, onOpened, onJob, onUpdate, onError, chromeConnected }: AppsTabProps) {
  const [flows, setFlows] = useState<FlowDef[] | null>(null);
  const [current, setCurrent] = useState<FlowDef | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api.flows().then(setFlows).catch(onError);
  }, [api, onError]);
  useEffect(load, [load]);

  useEffect(() => {
    if (!openFlow || !flows) return;
    const f = flows.find((x) => x.id === openFlow && x.available);
    if (f) setCurrent(f);
    onOpened();
  }, [openFlow, flows, onOpened]);

  const groups = useMemo(() => {
    const m = new Map<string, FlowDef[]>();
    for (const f of flows ?? []) m.set(f.group, [...(m.get(f.group) ?? []), f]);
    return [...m.entries()];
  }, [flows]);

  if (current) {
    return (
      <>
        {chromeConnected === false && CHROME_FLOWS.has(current.id) && <ChromeHint />}
        <FlowWizard
          key={current.id}
          api={api}
          flow={current}
          jobs={jobs}
          onClose={() => {
            setCurrent(null);
            load(); // remembered answers (last project, music app) may have changed
          }}
          onJob={onJob}
          onUpdate={onUpdate}
          onError={onError}
        />
      </>
    );
  }

  return (
    <div className="apps-tab">
      <div className="apps-tab-head">
        <h2>Apps</h2>
        <p>Pick an app, or just say its name (“YouTube”, “open Cursor”).</p>
      </div>
      {chromeConnected === false && <ChromeHint />}
      {flows === null && <p className="apps-loading">Loading apps…</p>}
      {groups.map(([group, list]) => (
        <section key={group} className="apps-group" aria-label={group}>
          <h3 className="apps-group-title">{group}</h3>
          <div className="apps-grid">
            {list.map((f) => (
              <button
                key={f.id}
                type="button"
                className={`app-tile ${f.available ? "" : "is-soon"}`}
                aria-disabled={!f.available}
                onClick={() => (f.available ? setCurrent(f) : setNotice(`${f.title}: ${f.coming}`))}
              >
                <TileIcon flow={f} />
                <span className="app-tile-title">{f.title}</span>
                <span className="app-tile-sub">{f.available ? f.subtitle : "Coming soon"}</span>
              </button>
            ))}
          </div>
        </section>
      ))}
      {notice && (
        <div className="apps-notice" role="status">
          <span>{notice}</span>
          <button type="button" className="icon-btn" aria-label="Dismiss" onClick={() => setNotice(null)}>
            <XIcon size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

interface WizardProps {
  api: Api;
  flow: FlowDef;
  jobs: Job[];
  onClose: () => void;
  onJob: (job: Job) => void;
  onUpdate: (job: Job) => void;
  onError: (e: unknown) => void;
}

function FlowWizard({ api, flow, jobs, onClose, onJob, onUpdate, onError }: WizardProps) {
  const [answers, setAnswers] = useState<Answers>(() => startAnswers(flow));
  const [jobId, setJobId] = useState<string | null>(null);
  const [ran, setRan] = useState(false); // the flow ran (possibly with no job: "Control what's playing")
  const [text, setText] = useState("");
  const [heard, setHeard] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const stage = ran ? null : nextStage(flow, answers);
  const job = jobs.find((j) => j.id === jobId);
  const results = flow.pick_results ? resultsOf(job) : [];
  const { step, total } = stepInfo(flow, answers);
  const remembered = flow.stages.filter((s) => s.default && answers[s.id] === s.default && s.id !== stage?.id);

  const run = useCallback(
    (a: Answers) => {
      setSending(true);
      api
        .runFlow(flow.id, a)
        .then((r) => {
          setRan(true);
          if (r.job) {
            setJobId(r.job.id);
            onJob(r.job);
          }
        })
        .catch((e) => {
          onError(e);
          setAnswers(startAnswers(flow)); // never leave the wizard on a blank screen
        })
        .finally(() => setSending(false));
    },
    [api, flow, onJob, onError],
  );

  const answer = useCallback(
    (s: FlowStage, value: string) => {
      const a = { ...answers, [s.id]: value };
      setAnswers(a);
      setText("");
      setHeard(null);
      if (!nextStage(flow, a)) run(a);
    },
    [answers, flow, run],
  );

  // Voice answer: PC1 transcribes only (no job); choices are matched here ("the second one").
  const onVoice = useCallback(
    (blob: Blob) => {
      if (!stage) return;
      api
        .transcribe(blob)
        .then(({ text: said }) => {
          if (stage.kind === "text") {
            if (said) answer(stage, said);
            else setHeard("I didn't catch that — try again or type it.");
            return;
          }
          const v = matchChoice(said, stage.options);
          if (v) answer(stage, v);
          else setHeard(said ? `Heard “${said}” — tap an option or try again.` : "I didn't catch that.");
        })
        .catch(onError);
    },
    [api, stage, answer, onError],
  );
  const mic = useRecorder(onVoice);
  const recording = mic.state === "recording";

  const control = (index: number) => {
    api.flowControl(flow.id, index, answers).then((j) => {
      setJobId(j.id);
      onJob(j);
    }).catch(onError);
  };

  const restart = () => {
    setAnswers(startAnswers(flow));
    setRan(false);
    setJobId(null);
  };

  return (
    <div className="flow-wizard" aria-label={`${flow.title} flow`}>
      <header className="flow-head">
        <button type="button" className="icon-btn" aria-label="Back to apps" onClick={onClose}>
          <ChevronLeftIcon size={20} />
        </button>
        <div className="flow-head-title">
          <TileIcon flow={flow} />
          <div>
            <div className="flow-title">{flow.title}</div>
            <div className="flow-step">{stage ? `Step ${step} of ${total}` : ran ? "Running" : "Ready"}</div>
          </div>
        </div>
      </header>

      {remembered.map((s) => (
        <button key={s.id} type="button" className="flow-chip"
          onClick={() => setAnswers(clearFrom(flow, answers, s.id))}>
          Using {s.options.find((o) => o.value === answers[s.id])?.label ?? answers[s.id]} · <u>change</u>
        </button>
      ))}

      {stage && (
        <section className="flow-stage" aria-live="polite">
          <h3 className="flow-question">{stage.question}</h3>
          {stage.kind === "choice" ? (
            <div className="flow-options" role="list">
              {stage.options.length === 0 && <p className="flow-empty">Nothing to choose from yet.</p>}
              {stage.options.map((o, i) => (
                <button
                  key={o.value}
                  type="button"
                  role="listitem"
                  className="flow-option"
                  disabled={!o.available || sending}
                  onClick={() => answer(stage, o.value)}
                >
                  <span className="flow-option-num">{i + 1}</span>
                  <span className="flow-option-text">
                    <span className="flow-option-label">{o.label}</span>
                    {o.hint && <span className="flow-option-hint">{o.hint}</span>}
                  </span>
                  <ChevronRightIcon size={18} />
                </button>
              ))}
            </div>
          ) : (
            <form
              className="flow-text"
              onSubmit={(e) => {
                e.preventDefault();
                if (text.trim()) answer(stage, text.trim());
              }}
            >
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder={stage.placeholder}
                maxLength={200}
                autoFocus
                aria-label={stage.question}
              />
              <button type="submit" className="flow-send" aria-label="Continue" disabled={!text.trim() || sending}>
                <SendIcon size={18} />
              </button>
            </form>
          )}
          {(mic.state === "idle" || recording) && (
            <button type="button" className={`flow-mic ${recording ? "is-recording" : ""}`} onClick={mic.toggle}>
              <MicIcon size={18} />
              <span>{recording ? "Listening… tap to send" : "Answer by voice"}</span>
            </button>
          )}
          {heard && <p className="flow-heard">{heard}</p>}
        </section>
      )}

      {ran && (
        <section className="flow-result">
          {job && (job.state === "done" || job.state === "failed" || job.state === "cancelled") && (
            <p className={`flow-status is-${job.state}`} role="status">
              {job.state === "done" ? job.summary || "Done" : job.error || "Stopped"}
            </p>
          )}
          {job && job.state !== "done" && job.state !== "failed" && job.state !== "cancelled" && (
            <ActiveJobCard job={job} api={api} onError={onError} onUpdate={onUpdate}
              onNewJob={(p) => p.then((j) => { setJobId(j.id); onJob(j); }).catch(onError)} />
          )}
          {results.length > 0 && (
            <div className="flow-results">
              <h3 className="flow-question">Pick one</h3>
              {results.slice(0, 5).map((r, i) => (
                <button key={r.url + i} type="button" className="flow-option"
                  onClick={() => api.sendText(`open result ${i + 1}`).then((j) => onJob(j)).catch(onError)}>
                  <span className="flow-option-num">{i + 1}</span>
                  <span className="flow-option-text">
                    <span className="flow-option-label">{r.title}</span>
                    <span className="flow-option-hint">{[r.channel || safeHost(r.url), r.length].filter(Boolean).join(" · ")}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
          {flow.controls.length > 0 && (
            <div className="flow-controls" aria-label="Controls">
              {flow.controls.map((c, i) => (
                <button key={c.label} type="button" className="flow-control" onClick={() => control(i)}>
                  {c.label}
                </button>
              ))}
            </div>
          )}
          {flow.stages.length > 0 && (
            <button type="button" className="flow-again" onClick={restart}>
              Start {flow.title} again
            </button>
          )}
        </section>
      )}

      {!stage && !ran && flow.stages.length === 0 && (
        <div className="flow-controls" aria-label="Controls">
          {flow.controls.map((c, i) => (
            <button key={c.label} type="button" className="flow-control" onClick={() => { setRan(true); control(i); }}>
              {c.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function safeHost(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return "";
  }
}
