import { useEffect, useMemo, useState } from "react";
import {
  confirmLeaveLedgerJob,
  createLeaveLedgerJob,
  exportLeaveLedgerXlsx,
  listConfirmedLeaveLedgerJobs,
  mergeLeaveLedgerJob,
  reviewLeaveLedgerJob,
  uploadLeaveLedgerSource,
  voidLeaveLedgerJob,
} from "../api.js";
import { useAuth } from "../auth.jsx";

const ROLE_LABEL = {
  travel: "出差申请",
  overtime: "加班申请",
  leave: "请假申请",
  punch: "打卡日报",
};

export default function LeaveLedgerPage() {
  const { user, hasPermission } = useAuth();
  const canRead = Boolean(user?.can_leave_ledger);
  const canWrite = canRead && hasPermission("leave_ledger:write");

  const [job, setJob] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [resolutions, setResolutions] = useState({});
  const [confirmedJobs, setConfirmedJobs] = useState([]);
  const [priorJobId, setPriorJobId] = useState("");

  useEffect(() => {
    if (!canRead) return;
    listConfirmedLeaveLedgerJobs()
      .then(setConfirmedJobs)
      .catch(() => setConfirmedJobs([]));
  }, [canRead, job?.id, job?.status]);

  const openWarnings = useMemo(() => {
    if (!job) return [];
    const resolved = { ...(job.resolved_warnings || {}), ...resolutions };
    return (job.warnings || []).filter((w) => {
      if (w.blocking === false) return false;
      const code = w.code || "";
      const detail = w.detail || {};
      if (code.startsWith("missing_source_")) {
        const role = detail.role || code.replace("missing_source_", "");
        return resolved.missing_sources?.[role] !== "accept";
      }
      if (code === "approval_not_passed") {
        const key = detail.key || "";
        return !["include", "exclude"].includes(resolved.approval_not_passed?.[key]);
      }
      if (code === "ot_half_day_mismatch" || code === "ot_missing_punch") {
        const key = `${detail.person}:${detail.date}`;
        return !["accept_full", "accept_half", "exclude"].includes(resolved[code]?.[key]);
      }
      if (code === "hq_address_unknown") {
        const key = `${detail.person}:${detail.start}:${detail.end}`;
        return resolved.hq_address_unknown?.[key] !== "accept";
      }
      return !resolved[code];
    });
  }, [job, resolutions]);

  const rows = job?.compute_result?.rows || [];

  async function onCreate(files) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      const next = await createLeaveLedgerJob([...files]);
      setJob(next);
      setResolutions({});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onAddSource(file) {
    if (!job || !file) return;
    setBusy(true);
    setError("");
    try {
      const next = await uploadLeaveLedgerSource(job.id, file);
      setJob(next);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onReview() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const next = await reviewLeaveLedgerJob(job.id, resolutions);
      setJob(next);
      setResolutions({});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      if (Object.keys(resolutions).length) {
        await reviewLeaveLedgerJob(job.id, resolutions);
      }
      const next = await confirmLeaveLedgerJob(job.id);
      setJob(next);
      setResolutions({});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onExport() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const blob = await exportLeaveLedgerXlsx(job.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `调休台账-${job.id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onVoid() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const next = await voidLeaveLedgerJob(job.id, "用户作废");
      setJob(next);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  async function onMerge() {
    if (!job || !priorJobId) {
      setError("请先选择一份已确认的上月台账");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const next = await mergeLeaveLedgerJob(job.id, priorJobId);
      setJob(next);
      setResolutions({});
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  function acceptMissing(role) {
    setResolutions((prev) => ({
      ...prev,
      missing_sources: { ...(prev.missing_sources || {}), [role]: "accept" },
    }));
  }

  function resolveApproval(key, action) {
    setResolutions((prev) => ({
      ...prev,
      approval_not_passed: { ...(prev.approval_not_passed || {}), [key]: action },
    }));
  }

  function resolveOt(code, key, action) {
    setResolutions((prev) => ({
      ...prev,
      [code]: { ...(prev[code] || {}), [key]: action },
    }));
  }

  if (!canRead) {
    return (
      <main className="page">
        <p className="muted">无调休台账读权限。</p>
      </main>
    );
  }

  return (
    <main className="page staffing-page">
      <header className="page-header">
        <h1>调休台账</h1>
        <p className="muted">上传出差 / 加班 / 请假 / 打卡四类企微导出，计算并导出太原调休台账。</p>
      </header>

      {error ? <p className="error-text">{error}</p> : null}

      {canWrite ? (
        <section className="card-block">
          <h2>上传源文件</h2>
          <input
            type="file"
            accept=".xlsx"
            multiple
            disabled={busy}
            onChange={(e) => {
              const files = e.target.files;
              if (files?.length) onCreate(files);
              e.target.value = "";
            }}
          />
          {job ? (
            <p className="muted" style={{ marginTop: 8 }}>
              补传单个文件：
              <input
                type="file"
                accept=".xlsx"
                disabled={busy || job.status === "confirmed" || job.status === "voided"}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) onAddSource(file);
                  e.target.value = "";
                }}
              />
            </p>
          ) : null}
        </section>
      ) : null}

      {job ? (
        <>
          <section className="card-block">
            <h2>任务状态</h2>
            <p>
              ID：<code>{job.id}</code> · 状态：<strong>{job.status}</strong>
            </p>
            <ul>
              {(job.sources || []).map((s) => (
                <li key={s.id}>
                  {ROLE_LABEL[s.role] || s.role} — {s.filename}
                  {s.parse_preview?.count != null ? `（${s.parse_preview.count} 条）` : ""}
                </li>
              ))}
            </ul>
            {canWrite && job.status !== "confirmed" && job.status !== "voided" ? (
              <div className="merge-prior" style={{ marginBottom: 12 }}>
                <label>
                  合并上月已确认台账{" "}
                  <select
                    value={priorJobId}
                    disabled={busy}
                    onChange={(e) => setPriorJobId(e.target.value)}
                  >
                    <option value="">请选择…</option>
                    {confirmedJobs
                      .filter((j) => j.id !== job.id)
                      .map((j) => (
                        <option key={j.id} value={j.id}>
                          {j.id.slice(0, 8)}… · {j.person_count} 人
                          {j.confirmed_at ? ` · ${String(j.confirmed_at).slice(0, 10)}` : ""}
                        </option>
                      ))}
                  </select>
                </label>{" "}
                <button type="button" disabled={busy || !priorJobId} onClick={onMerge}>
                  合并写回本月
                </button>
                <p className="muted" style={{ marginTop: 4 }}>
                  合并会按出差并集重算额度；同日加班/同段调休以上月已确认为准。合并后仍需确认。
                </p>
              </div>
            ) : null}
            <div className="button-row">
              {canWrite && job.status !== "confirmed" && job.status !== "voided" ? (
                <>
                  <button type="button" disabled={busy || openWarnings.length > 0} onClick={onConfirm}>
                    确认台账
                  </button>
                  <button type="button" disabled={busy || !Object.keys(resolutions).length} onClick={onReview}>
                    保存决议
                  </button>
                  <button type="button" disabled={busy} onClick={onVoid}>
                    作废
                  </button>
                </>
              ) : null}
              {job.status === "confirmed" ? (
                <button type="button" disabled={busy} onClick={onExport}>
                  下载台账 xlsx
                </button>
              ) : null}
            </div>
            {openWarnings.length > 0 ? (
              <p className="muted">还有 {openWarnings.length} 条未决议告警，确认前须处理。</p>
            ) : null}
          </section>

          {openWarnings.length > 0 ? (
            <section className="card-block">
              <h2>待复核告警</h2>
              <ul className="warning-list">
                {openWarnings.map((w, i) => {
                  const detail = w.detail || {};
                  return (
                    <li key={`${w.code}-${i}`}>
                      <div>
                        <strong>{w.code}</strong> — {w.message}
                      </div>
                      {w.code?.startsWith("missing_source_") && canWrite ? (
                        <button type="button" onClick={() => acceptMissing(detail.role)}>
                          接受缺失
                        </button>
                      ) : null}
                      {w.code === "approval_not_passed" && canWrite ? (
                        <span className="button-row">
                          <button type="button" onClick={() => resolveApproval(detail.key, "include")}>
                            纳入
                          </button>
                          <button type="button" onClick={() => resolveApproval(detail.key, "exclude")}>
                            排除
                          </button>
                        </span>
                      ) : null}
                      {(w.code === "ot_half_day_mismatch" || w.code === "ot_missing_punch") && canWrite ? (
                        <span className="button-row">
                          <button
                            type="button"
                            onClick={() =>
                              resolveOt(w.code, `${detail.person}:${detail.date}`, "exclude")
                            }
                          >
                            排除该日
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              resolveOt(w.code, `${detail.person}:${detail.date}`, "accept_half")
                            }
                          >
                            按半日记
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              resolveOt(w.code, `${detail.person}:${detail.date}`, "accept_full")
                            }
                          >
                            按满日记
                          </button>
                        </span>
                      ) : null}
                      {w.code === "hq_address_unknown" && canWrite ? (
                        <button
                          type="button"
                          onClick={() =>
                            setResolutions((prev) => ({
                              ...prev,
                              hq_address_unknown: {
                                ...(prev.hq_address_unknown || {}),
                                [`${detail.person}:${detail.start}:${detail.end}`]: "accept",
                              },
                            }))
                          }
                        >
                          已知晓
                        </button>
                      ) : null}
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}

          <section className="card-block">
            <h2>预览（{rows.length} 人）</h2>
            <div className="table-wrap">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>姓名</th>
                    <th>中心</th>
                    <th>部门</th>
                    <th>出差可调休</th>
                    <th>加班可调休</th>
                    <th>合计</th>
                    <th>调休起</th>
                    <th>调休止</th>
                    <th>已调休</th>
                    <th>剩余</th>
                    <th>备注</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const leaveSegs = r.leave_segments || [];
                    const leaveLabel =
                      leaveSegs.length > 1
                        ? leaveSegs
                            .map(
                              (s) =>
                                `${s.start || "?"}${s.end && s.end !== s.start ? `~${s.end}` : ""}(${s.used_days ?? ""})`
                            )
                            .join("；")
                        : "";
                    return (
                    <tr key={r.person_name}>
                      <td>{r.person_name}</td>
                      <td>{r.center}</td>
                      <td>{r.department}</td>
                      <td>{r.travel_comp_days}</td>
                      <td>{r.ot_comp_days}</td>
                      <td>{r.total_comp_days}</td>
                      <td title={leaveLabel || undefined}>
                        {r.leave_start ||
                          (leaveSegs[0] && leaveSegs[0].start) ||
                          ""}
                      </td>
                      <td title={leaveLabel || undefined}>
                        {r.leave_end ||
                          (leaveSegs[0] && leaveSegs[0].end) ||
                          ""}
                      </td>
                      <td>{r.used_comp_days}</td>
                      <td>{r.remaining_comp_days}</td>
                      <td>{r.remark}</td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : null}
    </main>
  );
}
