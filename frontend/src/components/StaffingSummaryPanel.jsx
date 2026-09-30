import { Fragment, useMemo, useState } from "react";
import StaffingChart from "./StaffingChart.jsx";

const KIND_ORDER = { internal_formal: 0, internal_contract: 1 };

/** Mirror backend calendar-gap stints when API omits them (stale process / old card). */
function buildStintsFromDates(dates, dateStages = {}) {
  const unique = [...new Set((dates || []).filter(Boolean))].sort();
  if (!unique.length) return [];
  const toTime = (iso) => new Date(`${iso}T00:00:00`).getTime();
  const day = 86400000;
  const stints = [];
  let start = unique[0];
  let end = unique[0];
  const push = (entry, exit) => {
    const days = Math.round((toTime(exit) - toTime(entry)) / day) + 1;
    const scoped = {};
    unique.forEach((iso) => {
      if (iso >= entry && iso <= exit) scoped[iso] = dateStages[iso] || null;
    });
    const stages = Object.values(scoped).reduce((acc, stage) => {
      const label = (stage || "").trim();
      if (!label) return acc;
      const hit = acc.find((row) => row.stage === label);
      if (hit) hit.days += 1;
      else acc.push({ stage: label, days: 1 });
      return acc;
    }, []);
    stints.push({
      index: stints.length + 1,
      entry_date: entry,
      exit_date: exit,
      days,
      stages,
      stage_label: stages
        .map((row) =>
          row.days !== days ? `${row.stage}(${row.days}天)` : row.stage,
        )
        .join("、"),
    });
  };
  for (let i = 1; i < unique.length; i += 1) {
    const cur = unique[i];
    if (toTime(cur) - toTime(end) === day) {
      end = cur;
      continue;
    }
    push(start, end);
    start = cur;
    end = cur;
  }
  push(start, end);
  return stints;
}

function resolveStints(p) {
  const dateStages = p.date_stages || {};
  const fromApi = Array.isArray(p.stints) ? p.stints : [];
  if (fromApi.length) {
    return fromApi.map((stint) => {
      if ((stint.stage_label || formatStages(stint.stages)) && (stint.stages || []).length) {
        return stint;
      }
      const entry = stint.entry_date;
      const exit = stint.exit_date;
      if (!entry || !exit) return stint;
      const scoped = {};
      Object.keys(dateStages).forEach((iso) => {
        if (iso >= entry && iso <= exit) scoped[iso] = dateStages[iso];
      });
      const stages = Object.values(scoped).reduce((acc, stage) => {
        const label = (stage || "").trim();
        if (!label) return acc;
        const hit = acc.find((row) => row.stage === label);
        if (hit) hit.days += 1;
        else acc.push({ stage: label, days: 1 });
        return acc;
      }, []);
      if (!stages.length) return { ...stint, stages: stint.stages || [], stage_label: stint.stage_label || "" };
      return {
        ...stint,
        stages,
        stage_label: stages
          .map((row) =>
            row.days !== stint.days ? `${row.stage}(${row.days}天)` : row.stage,
          )
          .join("、"),
      };
    });
  }
  return buildStintsFromDates(p.dates, dateStages);
}

function stintStageText(s) {
  return s?.stage_label || formatStages(s?.stages) || "—";
}

function formatStint(s) {
  const entry = (s.entry_date || "").slice(5);
  const exit = (s.exit_date || "").slice(5);
  const base = `${s.index}: ${entry}~${exit}（${s.days}天）`;
  return `${base} · 当前阶段：${stintStageText(s)}`;
}

function formatStages(stages) {
  if (!Array.isArray(stages) || !stages.length) return "";
  return stages
    .map((row) =>
      row.days ? `${row.stage}(${row.days}天)` : row.stage,
    )
    .filter(Boolean)
    .join("、");
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
  onMergeNames,
  onRepairRosterNames,
  exportBusy = false,
  mergeBusy = false,
  repairBusy = false,
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
  const suspects = summary.name_split_suspects || [];
  const rosterSuspects = summary.roster_name_suspects || [];
  const autoRoster = rosterSuspects.filter((s) => s.status === "auto");
  const unresolvedRoster = rosterSuspects.filter((s) => s.status === "unresolved");

  return (
    <div className={`staffing-summary-panel${compact ? " compact" : ""}`}>
      <div className="tool-card-title">人员投入汇总 · {title}</div>
      {autoRoster.length || unresolvedRoster.length ? (
        <div className="tool-card-collisions staffing-name-split-banner">
          <div className="tool-card-subtitle">花名册姓名（含机电服务处）</div>
          {autoRoster.length && onRepairRosterNames ? (
            <div className="collision-row">
              <p className="muted">
                {autoRoster.length} 个姓名可自动纠正（如 锐锋→陈锐锋、史承→史承志）
              </p>
              <div className="collision-actions">
                <button
                  type="button"
                  disabled={repairBusy}
                  onClick={(event) => {
                    event.stopPropagation();
                    onRepairRosterNames();
                  }}
                >
                  一键按花名册纠名
                </button>
              </div>
            </div>
          ) : null}
          {unresolvedRoster.map((item) => (
            <div className="collision-row" key={`roster-${item.token}`}>
              <strong>
                「{item.token}」· {item.person_kind_label || ""}
              </strong>
              <p className="muted">{item.message}</p>
              {(item.candidates || []).length && onMergeNames ? (
                <div className="collision-actions">
                  {item.candidates.slice(0, 5).map((c) => (
                    <button
                      key={c}
                      type="button"
                      disabled={mergeBusy}
                      onClick={(event) => {
                        event.stopPropagation();
                        onMergeNames(item.token, c);
                      }}
                    >
                      改为「{c}」
                    </button>
                  ))}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
      {suspects.length ? (
        <div className="tool-card-collisions staffing-name-split-banner">
          <div className="tool-card-subtitle">疑似 PDF 拆名 — 请复核</div>
          {suspects.map((item) => (
            <div
              className="collision-row"
              key={`${item.short_name}-${item.long_name}`}
            >
              <strong>
                「{item.short_name}」≈「{item.long_name}」
              </strong>
              <p className="muted">{item.message}</p>
              {onMergeNames ? (
                <div className="collision-actions">
                  <button
                    type="button"
                    disabled={mergeBusy}
                    onClick={(event) => {
                      event.stopPropagation();
                      onMergeNames(item.short_name, item.long_name);
                    }}
                  >
                    合并为「{item.long_name}」
                  </button>
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : null}
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
        正式 {formal.person_count || 0} 人 / {formal.person_day_total || 0} 人天 · 机电服务处{" "}
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
            <th>当前阶段</th>
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
            const stageText = formatStages(p.stages) || "—";
            const splitHit = suspects.some(
              (item) =>
                item.short_name === p.person_name || item.long_name === p.person_name,
            );
            return (
              <Fragment key={key}>
                <tr
                  className={`staffing-person-row${splitHit ? " staffing-name-split-row" : ""}`}
                  onClick={() => setOpenName(open ? null : key)}
                >
                  <td>
                    {p.person_name}
                    {splitHit ? (
                      <div className="staffing-inline-tag">疑似拆名</div>
                    ) : null}
                  </td>
                  <td>{p.person_kind_label || p.person_kind}</td>
                  <td>{p.days_on_site}</td>
                  <td>{stintCount}</td>
                  <td className="staffing-stage-cell">{stageText}</td>
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
                    <td colSpan={6} className="staffing-dates-cell">
                      <div className="staffing-stint-list">
                        <div className="muted">
                          在场摘要：共进场 {stintCount} 次，累计 {p.days_on_site}{" "}
                          天（连续日历日为一段；断日即新开段）
                        </div>
                        {stints.map((s) => (
                          <div key={s.index} className="staffing-stint-line">
                            <span>
                              第{s.index}次进场：{s.entry_date} 入场 → {s.exit_date}{" "}
                              离场（本段 {s.days} 天）
                            </span>
                            <span className="staffing-stint-stage">
                              当前阶段：{stintStageText(s)}
                            </span>
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
