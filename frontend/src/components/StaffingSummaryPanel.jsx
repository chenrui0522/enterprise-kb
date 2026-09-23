import { Fragment, useMemo, useState } from "react";
import StaffingChart from "./StaffingChart.jsx";

const KIND_ORDER = { internal_formal: 0, internal_contract: 1 };

/** Mirror backend calendar-gap stints when API omits them (stale process / old card). */
function buildStintsFromDates(dates) {
  const unique = [...new Set((dates || []).filter(Boolean))].sort();
  if (!unique.length) return [];
  const toTime = (iso) => new Date(`${iso}T00:00:00`).getTime();
  const day = 86400000;
  const stints = [];
  let start = unique[0];
  let end = unique[0];
  for (let i = 1; i < unique.length; i += 1) {
    const cur = unique[i];
    if (toTime(cur) - toTime(end) === day) {
      end = cur;
      continue;
    }
    stints.push({
      index: stints.length + 1,
      entry_date: start,
      exit_date: end,
      days: Math.round((toTime(end) - toTime(start)) / day) + 1,
    });
    start = cur;
    end = cur;
  }
  stints.push({
    index: stints.length + 1,
    entry_date: start,
    exit_date: end,
    days: Math.round((toTime(end) - toTime(start)) / day) + 1,
  });
  return stints;
}

function resolveStints(p) {
  const fromApi = Array.isArray(p.stints) ? p.stints : [];
  if (fromApi.length) return fromApi;
  return buildStintsFromDates(p.dates);
}

function formatStint(s) {
  const entry = (s.entry_date || "").slice(5);
  const exit = (s.exit_date || "").slice(5);
  return `${s.index}: ${entry}~${exit}（${s.days}天）`;
}

function stintsLabel(stints) {
  if (!stints.length) return "—";
  return stints.map(formatStint).join("；");
}

function sortPeople(people) {
  return [...(people || [])].sort((a, b) => {
    const ka = KIND_ORDER[a.person_kind] ?? 9;
    const kb = KIND_ORDER[b.person_kind] ?? 9;
    if (ka !== kb) return ka - kb;
    return String(a.person_name || "").localeCompare(String(b.person_name || ""), "zh");
  });
}

export default function StaffingSummaryPanel({
  summary,
  onExport,
  exportBusy = false,
  compact = false,
}) {
  const [openName, setOpenName] = useState(null);
  const people = useMemo(() => sortPeople(summary?.people), [summary?.people]);
  if (!summary) return null;
  const title =
    [summary.project_code, summary.project_name].filter(Boolean).join(" · ") ||
    summary.label ||
    "在场天数";
  const byKind = summary.by_kind || {};
  const formal = byKind.formal || {};
  const contract = byKind.contract || {};

  return (
    <div className={`staffing-summary-panel${compact ? " compact" : ""}`}>
      <div className="tool-card-title">人员投入汇总 · {title}</div>
      <div className="staffing-kpi-row">
        <div>
          <div className="staffing-kpi-value">{summary.person_count ?? 0}</div>
          <div className="muted">人数</div>
        </div>
        <div>
          <div className="staffing-kpi-value">{summary.person_day_total ?? 0}</div>
          <div className="muted">人天</div>
        </div>
        <div>
          <div className="staffing-kpi-value">
            {summary.date_from || "—"}
            {summary.date_to && summary.date_to !== summary.date_from
              ? ` ~ ${summary.date_to}`
              : ""}
          </div>
          <div className="muted">日期区间</div>
        </div>
      </div>
      <p className="muted staffing-kind-line">
        正式 {formal.person_count || 0} 人 / {formal.person_day_total || 0} 人天 · 外包性质{" "}
        {contract.person_count || 0} 人 / {contract.person_day_total || 0} 人天
      </p>
      <StaffingChart summary={summary} />
      <table className="tool-card-table">
        <thead>
          <tr>
            <th>姓名</th>
            <th>身份</th>
            <th>天数</th>
            <th>进场次数</th>
            <th>工期段</th>
          </tr>
        </thead>
        <tbody>
          {people.map((p) => {
            const key = `${p.person_name}-${p.person_kind}`;
            const open = openName === key;
            const stints = resolveStints(p);
            const stintCount = stints.length || Number(p.stint_count) || 0;
            const showExpand = stints.length > 3;
            return (
              <Fragment key={key}>
                <tr
                  className="staffing-person-row"
                  onClick={() => setOpenName(open ? null : key)}
                >
                  <td>{p.person_name}</td>
                  <td>{p.person_kind_label || p.person_kind}</td>
                  <td>{p.days_on_site}</td>
                  <td>{stintCount}</td>
                  <td className="staffing-stints-cell">
                    {showExpand && !open
                      ? `${stints
                          .slice(0, 3)
                          .map(formatStint)
                          .join("；")}…`
                      : stintsLabel(stints)}
                  </td>
                </tr>
                {open && stints.length ? (
                  <tr>
                    <td colSpan={5} className="staffing-dates-cell">
                      <div className="staffing-stint-list">
                        <div className="muted">
                          在场摘要：共进场 {stintCount} 次，累计 {p.days_on_site}{" "}
                          天（连续日历日为一段；断日即新开段）
                        </div>
                        {stints.map((s) => (
                          <div key={s.index}>
                            第{s.index}次进场：{s.entry_date} 入场 → {s.exit_date}{" "}
                            离场（本段 {s.days} 天）
                          </div>
                        ))}
                      </div>
                    </td>
                  </tr>
                ) : null}
              </Fragment>
            );
          })}
        </tbody>
      </table>
      {onExport ? (
        <div className="tool-card-actions">
          <button type="button" disabled={exportBusy} onClick={onExport}>
            导出 Excel
          </button>
        </div>
      ) : null}
    </div>
  );
}
