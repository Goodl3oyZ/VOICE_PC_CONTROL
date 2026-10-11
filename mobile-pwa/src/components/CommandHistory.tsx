import { useState, useMemo } from "react";
import type { Job } from "../api";
import { STATE_TH, formatDuration, formatTime, isActive } from "../labels";
import {
  AlertCircleIcon,
  CheckCircleIcon,
  ChevronDownIcon,
  ChevronRightIcon,
  ClockIcon,
  CpuIcon,
  HistoryIcon,
  SparklesIcon,
} from "./Icons";

interface CommandHistoryProps {
  jobs: Job[];
  onSelectJob?: (job: Job) => void;
}

type FilterTab = "all" | "active" | "done" | "failed";

export function CommandHistory({ jobs, onSelectJob }: CommandHistoryProps) {
  const [filter, setFilter] = useState<FilterTab>("all");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const filteredJobs = useMemo(() => {
    return jobs.filter((j) => {
      // Filter tab
      if (filter === "active" && !isActive(j)) return false;
      if (filter === "done" && j.state !== "done") return false;
      if (filter === "failed" && j.state !== "failed" && j.state !== "cancelled") return false;

      // Search query
      if (search.trim()) {
        const q = search.toLowerCase();
        const textMatch = (j.text || "").toLowerCase().includes(q);
        const summaryMatch = (j.summary || "").toLowerCase().includes(q);
        const toolMatch = j.steps.some((s) => s.tool.toLowerCase().includes(q));
        if (!textMatch && !summaryMatch && !toolMatch) return false;
      }
      return true;
    });
  }, [jobs, filter, search]);

  const toggleExpand = (id: string) => {
    setExpandedId((prev) => (prev === id ? null : id));
  };

  return (
    <section className="history-section" aria-label="ประวัติคำสั่ง">
      <div className="history-header">
        <div className="history-title-group">
          <HistoryIcon size={18} />
          <h2>ประวัติคำสั่งล่าสุด</h2>
          <span className="count-pill">{jobs.length}</span>
        </div>

        {/* Filter Tabs */}
        <div className="filter-tabs-row">
          <button
            type="button"
            className={`filter-tab-btn ${filter === "all" ? "active" : ""}`}
            onClick={() => setFilter("all")}
          >
            ทั้งหมด
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${filter === "active" ? "active" : ""}`}
            onClick={() => setFilter("active")}
          >
            กำลังทำ
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${filter === "done" ? "active" : ""}`}
            onClick={() => setFilter("done")}
          >
            สำเร็จ
          </button>
          <button
            type="button"
            className={`filter-tab-btn ${filter === "failed" ? "active" : ""}`}
            onClick={() => setFilter("failed")}
          >
            ปัญหา
          </button>
        </div>
      </div>

      {/* Search Bar */}
      {jobs.length > 3 && (
        <div className="history-search-bar">
          <input
            type="text"
            className="history-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="ค้นหาในประวัติคำสั่งหรือเครื่องมือ…"
            aria-label="ค้นหาคำสั่ง"
          />
          {search && (
            <button
              type="button"
              className="search-clear-btn"
              onClick={() => setSearch("")}
              aria-label="ล้างคำค้นหา"
            >
              ✕
            </button>
          )}
        </div>
      )}

      {/* History List or Empty state */}
      {filteredJobs.length === 0 ? (
        <div className="history-empty-state">
          {jobs.length === 0 ? (
            <>
              <SparklesIcon size={28} className="empty-icon" />
              <p className="empty-title">ยังไม่มีประวัติคำสั่ง</p>
              <p className="empty-sub">กดไมโครโฟนเพื่อพูด หรือพิมพ์คำสั่งด้านบนเพื่อเริ่มต้นใช้งาน</p>
            </>
          ) : (
            <>
              <p className="empty-title">ไม่พบรายการที่ตรงกับเงื่อนไข</p>
              <button type="button" className="btn-reset-filter" onClick={() => { setFilter("all"); setSearch(""); }}>
                แสดงทั้งหมด
              </button>
            </>
          )}
        </div>
      ) : (
        <ul className="history-items-list">
          {filteredJobs.map((j) => {
            const isExpanded = expandedId === j.id;
            return (
              <li
                key={j.id}
                className={`history-card state-${j.state} ${isExpanded ? "expanded" : ""}`}
              >
                <div
                  className="history-summary-row"
                  onClick={() => toggleExpand(j.id)}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      toggleExpand(j.id);
                    }
                  }}
                  aria-expanded={isExpanded}
                >
                  <div className="history-left-meta">
                    <span className="timestamp">
                      <ClockIcon size={12} />
                      {formatTime(j.created_at)}
                    </span>
                    <span className={`state-badge badge-${j.state}`}>
                      {j.state === "done" ? (
                        <CheckCircleIcon size={12} />
                      ) : j.state === "failed" || j.state === "cancelled" ? (
                        <AlertCircleIcon size={12} />
                      ) : (
                        <span className="pulse-indicator-small" />
                      )}
                      <span>{STATE_TH[j.state]}</span>
                    </span>
                  </div>

                  <div className="history-command-text">
                    {j.text || <em className="text-muted">(คำสั่งเสียง)</em>}
                  </div>

                  <div className="history-right-meta">
                    {j.timings_ms.total !== undefined && (
                      <span className="duration-tag">{formatDuration(j.timings_ms.total)}</span>
                    )}
                    <span className="expand-chevron">
                      {isExpanded ? <ChevronDownIcon size={16} /> : <ChevronRightIcon size={16} />}
                    </span>
                  </div>
                </div>

                {/* Quick tool pipeline preview */}
                {j.steps && j.steps.length > 0 && !isExpanded && (
                  <div className="history-tools-preview">
                    <CpuIcon size={12} />
                    <span>{j.steps.map((s) => s.tool).join(" → ")}</span>
                  </div>
                )}

                {/* Expanded Details */}
                {isExpanded && (
                  <div className="history-expanded-body">
                    {j.summary && (
                      <div className="expanded-field">
                        <span className="field-label">ผลลัพธ์:</span>
                        <div className="field-value summary-text">{j.summary}</div>
                      </div>
                    )}

                    {j.error && (
                      <div className="expanded-field error-field">
                        <span className="field-label">ข้อผิดพลาด:</span>
                        <div className="field-value error-text">{j.error}</div>
                      </div>
                    )}

                    {j.steps && j.steps.length > 0 && (
                      <div className="expanded-field">
                        <span className="field-label">ขั้นตอนการรันเครื่องมือ ({j.steps.length}):</span>
                        <div className="expanded-steps-list">
                          {j.steps.map((st, idx) => (
                            <div key={idx} className="expanded-step-item">
                              <span className="step-badge-tool">{st.tool}</span>
                              {st.arguments && Object.keys(st.arguments).length > 0 && (
                                <code className="step-args-preview">
                                  {JSON.stringify(st.arguments)}
                                </code>
                              )}
                              {st.result && (
                                <span className={`step-status-chip ${st.result.ok ? "ok" : "fail"}`}>
                                  {st.result.ok ? "สำเร็จ" : "ล้มเหลว"}
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {onSelectJob && (
                      <div className="expanded-actions">
                        <button
                          type="button"
                          className="btn-select-job"
                          onClick={() => onSelectJob(j)}
                        >
                          ตรวจสอบคำสั่งนี้
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
