import { useMemo, useState, type ComponentType } from "react";
import type { Job } from "../api";
import { dayLabel, formatClock, isActive, jobHeadline, jobKind, type JobKind } from "../labels";
import {
  AlertCircleIcon,
  ChevronRightIcon,
  CpuIcon,
  GridIcon,
  MonitorIcon,
  NextIcon,
  PlayPauseIcon,
  PowerIcon,
  SearchIcon,
  SparklesIcon,
  TerminalIcon,
  VolumeIcon,
} from "./Icons";

interface CommandHistoryProps {
  jobs: Job[];
  onSelectJob?: (job: Job) => void;
}

const KIND_ICON: Record<JobKind, ComponentType<{ size?: number }>> = {
  media: PlayPauseIcon,
  skip: NextIcon,
  volume: VolumeIcon,
  search: SearchIcon,
  app: GridIcon,
  screen: MonitorIcon,
  power: PowerIcon,
  code: TerminalIcon,
  status: CpuIcon,
  chat: SparklesIcon,
};

/** Activity (owner feedback 2026-10-14): a timeline by day that says what happened, not which tool ran. */
export function CommandHistory({ jobs, onSelectJob }: CommandHistoryProps) {
  const [search, setSearch] = useState("");

  const days = useMemo(() => {
    const q = search.trim().toLowerCase();
    const groups: { label: string; jobs: Job[] }[] = [];
    for (const j of jobs) {
      if (q && !`${j.text} ${j.summary} ${j.error ?? ""}`.toLowerCase().includes(q)) continue;
      const label = dayLabel(j.created_at);
      const last = groups[groups.length - 1];
      if (last?.label === label) last.jobs.push(j);
      else groups.push({ label, jobs: [j] });
    }
    return groups;
  }, [jobs, search]);

  return (
    <section className="tl" aria-label="Activity">
      <h2 className="tl-title">Activity</h2>

      {jobs.length > 3 && (
        <div className="history-search-bar">
          <SearchIcon size={16} className="tl-search-icon" />
          <input
            type="text"
            className="history-search-input tl-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search what you said or what happened"
            aria-label="Search activity"
          />
          {search && (
            <button type="button" className="search-clear-btn" onClick={() => setSearch("")} aria-label="Clear search">
              ✕
            </button>
          )}
        </div>
      )}

      {days.length === 0 ? (
        <div className="history-empty-state">
          {jobs.length === 0 ? (
            <>
              <SparklesIcon size={28} className="empty-icon" />
              <p className="empty-title">Nothing yet</p>
              <p className="empty-sub">What you ask your PC to do will show up here</p>
            </>
          ) : (
            <>
              <p className="empty-title">Nothing matches “{search}”</p>
              <button type="button" className="btn-reset-filter" onClick={() => setSearch("")}>
                Show everything
              </button>
            </>
          )}
        </div>
      ) : (
        days.map((day) => (
          <div key={day.label} className="tl-day">
            <h3 className="tl-day-label">{day.label}</h3>
            <ul className="tl-list">
              {day.jobs.map((j) => {
                const failed = j.state === "failed" || j.state === "cancelled";
                const waiting = j.state === "clarifying" || j.state === "awaiting_confirm";
                const tone = failed ? "bad" : waiting ? "wait" : isActive(j) ? "busy" : "ok";
                const Icon = failed ? AlertCircleIcon : KIND_ICON[jobKind(j)];
                return (
                  <li key={j.id}>
                    <button
                      type="button"
                      className={`tl-item tone-${tone}`}
                      onClick={() => onSelectJob?.(j)}
                      title="Open details"
                    >
                      <span className="tl-icon" aria-hidden="true">
                        <Icon size={18} />
                      </span>
                      <span className="tl-body">
                        <span className="tl-headline">{jobHeadline(j)}</span>
                        {j.text && (
                          <span className="tl-said">
                            {j.source === "audio" ? "You said" : "You typed"}: {j.text}
                          </span>
                        )}
                        {waiting && <span className="tl-cta">Needs you — tap to answer</span>}
                      </span>
                      <span className="tl-meta">
                        <time className="tl-time">{formatClock(j.created_at)}</time>
                        <ChevronRightIcon size={16} className="tl-chevron" />
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </div>
        ))
      )}
    </section>
  );
}
