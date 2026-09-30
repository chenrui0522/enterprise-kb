import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import BrandLogo, { BRAND_PRODUCT_NAME } from "../BrandLogo.jsx";
import {
  chatToolAction,
  createConversation,
  deleteConversation,
  exportLeaveLedgerXlsx,
  exportStaffingXlsx,
  getConversationMemory,
  getMessages,
  getStaffingSummary,
  listChatTools,
  listConversations,
  listMyStaffingProjects,
  mergeStaffingNames,
  repairStaffingRosterNames,
  streamChat,
  submitFeedback,
  updateConversationTitle,
  uploadChatAttachment,
} from "../api.js";
import { useAuth } from "../auth.jsx";
import StaffingSummaryPanel from "../components/StaffingSummaryPanel.jsx";

const SUGGESTIONS = [
  "ZB-100 打印机的保修期是多久？",
  "ZB-100 和 ZB-200 的保修有什么区别？",
  "打印机卡纸了应该怎么办？",
  "如何申请保修？",
];

const STORAGE_KEY = "kb:lastConversationId";

/** Prefer live project summary so stage fields stay current on old chat cards. */
function LiveStaffingSummary({ card }) {
  const [summary, setSummary] = useState(card);
  const [exportBusy, setExportBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [repairBusy, setRepairBusy] = useState(false);
  const [error, setError] = useState("");
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const projectId = card?.project_id;
    if (!projectId) {
      setSummary(card);
      return undefined;
    }
    let cancelled = false;
    getStaffingSummary(projectId)
      .then((live) => {
        if (!cancelled) setSummary({ ...card, ...live, type: "staffing_summary" });
      })
      .catch((err) => {
        if (!cancelled) {
          setSummary(card);
          setError(err.message || "刷新汇总失败，显示会话内缓存");
        }
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card?.project_id, tick]);

  return (
    <div className="tool-card">
      {error ? <p className="muted tool-card-hint">{error}</p> : null}
      <StaffingSummaryPanel
        summary={summary}
        compact
        exportBusy={exportBusy}
        mergeBusy={mergeBusy}
        repairBusy={repairBusy}
        onMergeNames={
          summary?.project_id
            ? async (fromName, toName) => {
                setMergeBusy(true);
                setError("");
                try {
                  await mergeStaffingNames(summary.project_id, fromName, toName);
                  setTick((n) => n + 1);
                } catch (err) {
                  setError(err.message || "合并失败");
                } finally {
                  setMergeBusy(false);
                }
              }
            : undefined
        }
        onRepairRosterNames={
          summary?.project_id
            ? async () => {
                setRepairBusy(true);
                setError("");
                try {
                  const result = await repairStaffingRosterNames(summary.project_id);
                  setTick((n) => n + 1);
                  if (result.unresolved_count) {
                    setError(
                      `已自动纠正 ${result.applied_count} 个；仍有 ${result.unresolved_count} 个需人工裁定`,
                    );
                  }
                } catch (err) {
                  setError(err.message || "花名册纠名失败");
                } finally {
                  setRepairBusy(false);
                }
              }
            : undefined
        }
        onExport={
          summary?.project_id
            ? async () => {
                setExportBusy(true);
                try {
                  await exportStaffingXlsx(summary.project_id);
                } catch (err) {
                  setError(err.message || "导出失败");
                } finally {
                  setExportBusy(false);
                }
              }
            : undefined
        }
      />
    </div>
  );
}

function RichText({ text }) {
  const parts = String(text || "").split(/\*\*(.+?)\*\*/g);
  return parts.map((part, index) => (index % 2 === 1 ? <strong key={index}>{part}</strong> : part));
}

function StaffingBatchCard({ card, disabled, onConfirm }) {
  const needsProject = !card.project_id;
  const collisions = card.collisions || [];
  const rosterUnresolved = card.roster_unresolved || [];
  const rosterUnavailable = Boolean(card.roster_unavailable);
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(card.project_id || "");
  const [loadError, setLoadError] = useState("");
  const [collisionChoices, setCollisionChoices] = useState(() => {
    const init = {};
    for (const c of collisions) {
      if (c.person_name) init[c.person_name] = { action: "split" };
    }
    return init;
  });
  const [rosterChoices, setRosterChoices] = useState({});

  useEffect(() => {
    if (!needsProject) return undefined;
    let cancelled = false;
    listMyStaffingProjects()
      .then((rows) => {
        if (cancelled) return;
        const preferred = card.project_candidates || [];
        const merged = [...preferred];
        for (const row of rows || []) {
          if (!merged.some((p) => p.id === row.id)) merged.push(row);
        }
        setProjects(merged);
        if (!projectId && preferred.length === 1) setProjectId(preferred[0].id);
        else if (!projectId && merged.length === 1) setProjectId(merged[0].id);
      })
      .catch((err) => {
        if (!cancelled) setLoadError(err.message || "无法加载项目列表");
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [needsProject, card.batch_id]);

  const collisionsReady =
    collisions.length === 0 ||
    collisions.every((c) => {
      const choice = collisionChoices[c.person_name];
      if (!choice) return false;
      if (choice.action === "split") return true;
      return choice.action === "merge" && choice.keep_kind;
    });

  const rosterReady =
    !rosterUnavailable &&
    (rosterUnresolved.length === 0 ||
      rosterUnresolved.every((r) => {
        const choice = rosterChoices[r.token];
        if (!choice) return false;
        if (choice.action === "discard") return true;
        return (
          (choice.action === "select_roster_name" || choice.action === "rename") &&
          Boolean(choice.name)
        );
      }));

  const setCollisionAction = (name, action) => {
    setCollisionChoices((prev) => ({
      ...prev,
      [name]:
        action === "merge"
          ? { action: "merge", keep_kind: prev[name]?.keep_kind || "internal_formal" }
          : { action: "split" },
    }));
  };

  return (
    <div className="tool-card">
      <div className="tool-card-title">人员投入 · 导入批次</div>
      <p className="muted">
        {card.filename} · {card.status}
        {card.warning_count ? ` · 告警 ${card.warning_count}` : ""}
      </p>
      {needsProject ? (
        <div className="tool-card-project">
          <label>
            选定项目
            <select
              value={projectId}
              disabled={disabled}
              onChange={(e) => setProjectId(e.target.value)}
            >
              <option value="">请选择要入库的项目</option>
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </select>
          </label>
          {card.match_codes?.length ? (
            <p className="muted tool-card-hint">文件识别项目码：{card.match_codes.join("、")}</p>
          ) : null}
          {loadError ? <p className="tool-card-error">{loadError}</p> : null}
          {!loadError && projects.length === 0 ? (
            <p className="tool-card-error">你名下没有可导入的项目，请联系管理员授权项目成员。</p>
          ) : null}
        </div>
      ) : null}
      {collisions.length ? (
        <div className="tool-card-collisions">
          <div className="tool-card-subtitle">同名双身份 — 请裁定</div>
          {collisions.map((c) => {
            const choice = collisionChoices[c.person_name] || { action: "split" };
            return (
              <div className="collision-row" key={c.person_name}>
                <div className="collision-name">{c.person_name}</div>
                <p className="muted">{c.message}</p>
                <div className="collision-actions">
                  <label>
                    <input
                      type="radio"
                      name={`col-${card.batch_id}-${c.person_name}`}
                      checked={choice.action === "split"}
                      disabled={disabled}
                      onChange={() => setCollisionAction(c.person_name, "split")}
                    />
                    不同人（分列）
                  </label>
                  <label>
                    <input
                      type="radio"
                      name={`col-${card.batch_id}-${c.person_name}`}
                      checked={choice.action === "merge"}
                      disabled={disabled}
                      onChange={() => setCollisionAction(c.person_name, "merge")}
                    />
                    同一人，保留
                  </label>
                  {choice.action === "merge" ? (
                    <select
                      value={choice.keep_kind || "internal_formal"}
                      disabled={disabled}
                      onChange={(e) =>
                        setCollisionChoices((prev) => ({
                          ...prev,
                          [c.person_name]: { action: "merge", keep_kind: e.target.value },
                        }))
                      }
                    >
                      <option value="internal_formal">正式我司</option>
                      <option value="internal_contract">机电服务处</option>
                    </select>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
      {rosterUnavailable ? (
        <p className="tool-card-error">
          人员信息花名册不可用，请配置 KB_STAFFING_ROSTER_PATH 后重新导入。
        </p>
      ) : null}
      {rosterUnresolved.length ? (
        <div className="tool-card-collisions">
          <div className="collision-name">花名册无法确认</div>
          {rosterUnresolved.map((r) => {
            const choice = rosterChoices[r.token] || {};
            return (
              <div className="collision-row" key={r.token}>
                <div className="collision-name">{r.token}</div>
                <p className="muted">{r.message}</p>
                <div className="collision-actions">
                  {(r.candidates || []).length ? (
                    <label>
                      选定
                      <select
                        value={choice.action === "select_roster_name" ? choice.name || "" : ""}
                        disabled={disabled}
                        onChange={(e) => {
                          const name = e.target.value;
                          if (!name) return;
                          setRosterChoices((prev) => ({
                            ...prev,
                            [r.token]: { action: "select_roster_name", name },
                          }));
                        }}
                      >
                        <option value="">请选择</option>
                        {r.candidates.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <label>
                    改名
                    <input
                      type="text"
                      disabled={disabled}
                      value={choice.action === "rename" ? choice.name || "" : ""}
                      onChange={(e) =>
                        setRosterChoices((prev) => ({
                          ...prev,
                          [r.token]: { action: "rename", name: e.target.value },
                        }))
                      }
                    />
                  </label>
                  <label>
                    <input
                      type="radio"
                      name={`chat-roster-discard-${r.token}`}
                      disabled={disabled}
                      checked={choice.action === "discard"}
                      onChange={() =>
                        setRosterChoices((prev) => ({
                          ...prev,
                          [r.token]: { action: "discard" },
                        }))
                      }
                    />
                    丢弃
                  </label>
                </div>
              </div>
            );
          })}
        </div>
      ) : null}
      {card.warnings?.length ? (
        <ul className="tool-card-list">
          {card.warnings
            .filter(
              (w) =>
                w.code !== "name_kind_collision" &&
                w.code !== "roster_name_unresolved" &&
                w.code !== "roster_unavailable" &&
                w.code !== "roster_name_corrected",
            )
            .slice(0, 8)
            .map((w, i) => (
              <li key={`${w.code}-${i}`}>
                {w.code}: {w.message}
              </li>
            ))}
        </ul>
      ) : null}
      <div className="tool-card-actions">
        {(card.actions || []).map((a) => (
          <button
            key={a.id}
            type="button"
            disabled={
              disabled ||
              (a.id === "ack_and_confirm" &&
                ((needsProject && !projectId) || !collisionsReady || !rosterReady))
            }
            onClick={() =>
              onConfirm(a.id, {
                batch_id: card.batch_id,
                project_id: projectId || card.project_id || null,
                name_kind_collision: collisions.length ? collisionChoices : undefined,
                roster_name_unresolved: rosterUnresolved.length
                  ? rosterChoices
                  : undefined,
              })
            }
          >
            {a.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function leaveWarningStillOpen(w, resolved) {
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
}

function mergeLeaveResolutions(base, local) {
  const out = { ...(base || {}) };
  for (const [k, v] of Object.entries(local || {})) {
    if (v && typeof v === "object" && !Array.isArray(v) && out[k] && typeof out[k] === "object") {
      out[k] = { ...out[k], ...v };
    } else {
      out[k] = v;
    }
  }
  return out;
}

function LeaveLedgerJobCard({ card, disabled, onAction }) {
  const [error, setError] = useState("");
  const [exportBusy, setExportBusy] = useState(false);
  const [resolutions, setResolutions] = useState({});
  const [busy, setBusy] = useState(false);

  const roles = card.roles || [];
  const needRolePick = Boolean(card.need_role_pick);
  const mergedResolved = useMemo(
    () => mergeLeaveResolutions(card.resolved_warnings, resolutions),
    [card.resolved_warnings, resolutions]
  );
  const openWarnings = useMemo(
    () => (card.warnings || []).filter((w) => leaveWarningStillOpen(w, mergedResolved)),
    [card.warnings, mergedResolved]
  );
  const otMissing = openWarnings.filter((w) => w.code === "ot_missing_punch");
  const otHalf = openWarnings.filter((w) => w.code === "ot_half_day_mismatch");
  const hasLocalResolutions = Object.keys(resolutions).length > 0;
  const serverOpenCount =
    typeof card.open_blocking_count === "number" ? card.open_blocking_count : null;
  // After local edits, trust the filtered list; otherwise prefer server count so a
  // truncated/stale card cannot enable confirm while confirm_job would still fail.
  const pendingCount = hasLocalResolutions
    ? openWarnings.length
    : serverOpenCount != null
      ? serverOpenCount
      : openWarnings.length;
  const canConfirm =
    !needRolePick &&
    (card.status === "parsed" || card.status === "needs_review") &&
    pendingCount === 0;

  const acceptMissing = (role) => {
    setResolutions((prev) => ({
      ...prev,
      missing_sources: { ...(prev.missing_sources || {}), [role]: "accept" },
    }));
  };

  const resolveApproval = (key, action) => {
    setResolutions((prev) => ({
      ...prev,
      approval_not_passed: { ...(prev.approval_not_passed || {}), [key]: action },
    }));
  };

  const resolveOt = (code, key, action) => {
    setResolutions((prev) => ({
      ...prev,
      [code]: { ...(prev[code] || {}), [key]: action },
    }));
  };

  const bulkResolveOt = (code, action) => {
    const list = openWarnings.filter((w) => w.code === code);
    if (!list.length) return;
    setResolutions((prev) => {
      const bucket = { ...(prev[code] || {}) };
      for (const w of list) {
        const d = w.detail || {};
        bucket[`${d.person}:${d.date}`] = action;
      }
      return { ...prev, [code]: bucket };
    });
  };

  const run = async (action, payload = {}) => {
    setError("");
    setBusy(true);
    try {
      await onAction(action, {
        job_id: card.job_id,
        ...payload,
      });
      setResolutions({});
    } catch (err) {
      setError(err.message || "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const onExport = async () => {
    setExportBusy(true);
    setError("");
    try {
      await run("leave_ledger.export", {});
      const blob = await exportLeaveLedgerXlsx(card.job_id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `调休台账-${card.job_id}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err.message || "导出失败");
    } finally {
      setExportBusy(false);
    }
  };

  const onSubmitReview = async () => {
    if (!hasLocalResolutions) return;
    await run("leave_ledger.review", { resolutions });
  };

  const onConfirm = async () => {
    if (!window.confirm("确认将该调休台账标记为已确认？确认后可导出正式台账。")) return;
    await run("leave_ledger.confirm", {
      confirmed: true,
      resolutions: hasLocalResolutions ? resolutions : undefined,
    });
  };

  const onVoid = async () => {
    if (!window.confirm("确认作废该调休台账任务？此操作不可撤销。")) return;
    await run("leave_ledger.void", { confirmed: true, reason: "对话中作废" });
  };

  const actionsDisabled = disabled || busy || exportBusy;

  return (
    <div className="tool-card">
      <div className="tool-card-title">调休台账 · 任务进度</div>
      <p className="muted">
        {card.job_id?.slice(0, 8)}… · {card.status}
        {pendingCount ? ` · 待决议 ${pendingCount}` : ""}
        {card.row_count != null ? ` · ${card.row_count} 人` : ""}
      </p>
      {card.note ? <p className="muted tool-card-hint">{card.note}</p> : null}
      {card.pending_filename ? (
        <p className="tool-card-hint">待指定角色：{card.pending_filename}</p>
      ) : null}
      <ul className="tool-card-list">
        {roles.map((r) => (
          <li key={r.role}>
            {r.filled ? "✓" : "○"} {r.label}
            {r.filename ? ` · ${r.filename}` : " · 未上传"}
          </li>
        ))}
      </ul>
      {pendingCount > 0 && openWarnings.length === 0 ? (
        <p className="tool-card-error">
          仍有 {pendingCount} 条未决议告警未展示在本卡片中。请重新触发任务卡片，或打开调休台账页处理。
        </p>
      ) : null}
      {openWarnings.length ? (
        <>
          <p className="muted tool-card-hint">
            确认前须处理下列告警（可先批量处理同类项）。
          </p>
          <div className="tool-card-actions">
            {otMissing.length ? (
              <>
                <button
                  type="button"
                  disabled={actionsDisabled}
                  onClick={() => bulkResolveOt("ot_missing_punch", "exclude")}
                >
                  缺打卡全部排除（{otMissing.length}）
                </button>
                <button
                  type="button"
                  disabled={actionsDisabled}
                  onClick={() => bulkResolveOt("ot_missing_punch", "accept_full")}
                >
                  缺打卡全部按满日记
                </button>
              </>
            ) : null}
            {otHalf.length ? (
              <>
                <button
                  type="button"
                  disabled={actionsDisabled}
                  onClick={() => bulkResolveOt("ot_half_day_mismatch", "exclude")}
                >
                  半天不符全部排除（{otHalf.length}）
                </button>
                <button
                  type="button"
                  disabled={actionsDisabled}
                  onClick={() => bulkResolveOt("ot_half_day_mismatch", "accept_full")}
                >
                  半天不符全部按满日记
                </button>
              </>
            ) : null}
            {openWarnings.some((w) => w.code === "approval_not_passed") ? (
              <>
                <button
                  type="button"
                  disabled={actionsDisabled}
                  onClick={() => {
                    const list = openWarnings.filter((w) => w.code === "approval_not_passed");
                    setResolutions((prev) => {
                      const bucket = { ...(prev.approval_not_passed || {}) };
                      for (const w of list) {
                        const key = (w.detail || {}).key || "";
                        if (key) bucket[key] = "exclude";
                      }
                      return { ...prev, approval_not_passed: bucket };
                    });
                  }}
                >
                  未通过审批全部排除
                </button>
              </>
            ) : null}
          </div>
          <ul className="tool-card-list">
            {openWarnings.slice(0, 40).map((w, i) => {
              const detail = w.detail || {};
              const code = w.code || "";
              const hasSpecial =
                code.startsWith("missing_source_") ||
                code === "approval_not_passed" ||
                code === "ot_half_day_mismatch" ||
                code === "ot_missing_punch" ||
                code === "hq_address_unknown";
              return (
                <li key={`${code}-${i}`}>
                  <div>
                    <strong>{code}</strong> — {w.message}
                  </div>
                  {code.startsWith("missing_source_") ? (
                    <button
                      type="button"
                      className="linkish"
                      disabled={actionsDisabled}
                      onClick={() => {
                        const role = detail.role || code.replace("missing_source_", "");
                        acceptMissing(role);
                      }}
                    >
                      接受缺失
                    </button>
                  ) : null}
                  {code === "approval_not_passed" ? (
                    <span className="tool-card-actions">
                      <button
                        type="button"
                        className="linkish"
                        disabled={actionsDisabled}
                        onClick={() => resolveApproval(detail.key || "", "include")}
                      >
                        纳入
                      </button>
                      <button
                        type="button"
                        className="linkish"
                        disabled={actionsDisabled}
                        onClick={() => resolveApproval(detail.key || "", "exclude")}
                      >
                        排除
                      </button>
                    </span>
                  ) : null}
                  {code === "ot_half_day_mismatch" || code === "ot_missing_punch" ? (
                    <span className="tool-card-actions">
                      <button
                        type="button"
                        className="linkish"
                        disabled={actionsDisabled}
                        onClick={() =>
                          resolveOt(code, `${detail.person}:${detail.date}`, "exclude")
                        }
                      >
                        排除该日
                      </button>
                      <button
                        type="button"
                        className="linkish"
                        disabled={actionsDisabled}
                        onClick={() =>
                          resolveOt(code, `${detail.person}:${detail.date}`, "accept_half")
                        }
                      >
                        按半日记
                      </button>
                      <button
                        type="button"
                        className="linkish"
                        disabled={actionsDisabled}
                        onClick={() =>
                          resolveOt(code, `${detail.person}:${detail.date}`, "accept_full")
                        }
                      >
                        按满日记
                      </button>
                    </span>
                  ) : null}
                  {code === "hq_address_unknown" ? (
                    <button
                      type="button"
                      className="linkish"
                      disabled={actionsDisabled}
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
                  {!hasSpecial ? (
                    <button
                      type="button"
                      className="linkish"
                      disabled={actionsDisabled}
                      onClick={() =>
                        setResolutions((prev) => ({
                          ...prev,
                          [code]: true,
                        }))
                      }
                    >
                      已知晓
                    </button>
                  ) : null}
                </li>
              );
            })}
            {openWarnings.length > 40 ? (
              <li className="muted">另有 {openWarnings.length - 40} 条，请用上方批量按钮处理。</li>
            ) : null}
          </ul>
        </>
      ) : null}
      {error ? <p className="tool-card-error">{error}</p> : null}
      <div className="tool-card-actions">
        {needRolePick
          ? (card.actions || [])
              .filter((a) => String(a.id).startsWith("leave_ledger.pick_role"))
              .map((a) => (
                <button
                  key={a.id}
                  type="button"
                  disabled={actionsDisabled}
                  onClick={() => run(a.id, { role: a.id.split(":")[1] })}
                >
                  {a.label}
                </button>
              ))
          : null}
        {!needRolePick && hasLocalResolutions ? (
          <button type="button" disabled={actionsDisabled} onClick={onSubmitReview}>
            提交复核决议
          </button>
        ) : null}
        {!needRolePick && canConfirm ? (
          <button type="button" disabled={actionsDisabled} onClick={onConfirm}>
            确认台账
          </button>
        ) : null}
        {!needRolePick && card.status === "confirmed" ? (
          <button type="button" disabled={actionsDisabled} onClick={onExport}>
            {exportBusy ? "导出中…" : "导出 Excel"}
          </button>
        ) : null}
        {!needRolePick && card.status !== "voided" ? (
          <button type="button" disabled={actionsDisabled} onClick={onVoid}>
            作废
          </button>
        ) : null}
      </div>
    </div>
  );
}

function persistConversationId(id) {
  if (!id) {
    localStorage.removeItem(STORAGE_KEY);
    return;
  }
  localStorage.setItem(STORAGE_KEY, id);
}

export default function ChatPage() {
  const { hasPermission } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [conversations, setConversations] = useState([]);
  const [conversationId, setConversationId] = useState(null);
  const [conversationTitle, setConversationTitle] = useState("新对话");
  const [editingTitleId, setEditingTitleId] = useState(null);
  const [editingTitleDraft, setEditingTitleDraft] = useState("");
  const [editingTitleSurface, setEditingTitleSurface] = useState(null); // "list" | "header"
  const editingTitleIdRef = useRef(null);
  const editingTitleDraftRef = useRef("");
  const [messages, setMessages] = useState([]);
  const [memory, setMemory] = useState(null);
  const [sessionError, setSessionError] = useState("");
  const [lightbox, setLightbox] = useState(null);
  const [tools, setTools] = useState([]);
  const [activeTool, setActiveTool] = useState("");
  const [toolMenuOpen, setToolMenuOpen] = useState(false);
  const [attachment, setAttachment] = useState(null);
  const [attachBusy, setAttachBusy] = useState(false);
  const galleryFor = (message) => (message.citations || []).flatMap((item) => item.images || []);

  useEffect(() => {
    if (!lightbox) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") setLightbox(null);
      if (event.key === "ArrowRight") {
        setLightbox((prev) => (prev ? { ...prev, index: (prev.index + 1) % prev.images.length } : prev));
      }
      if (event.key === "ArrowLeft") {
        setLightbox((prev) => (prev ? { ...prev, index: (prev.index - 1 + prev.images.length) % prev.images.length } : prev));
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [lightbox]);

  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const textareaRef = useRef(null);
  const bottomRef = useRef(null);
  const restoredRef = useRef(false);

  const refreshConversations = async () => {
    const rows = await listConversations();
    setConversations(rows);
    return rows;
  };

  const loadMemory = async (id) => {
    if (!id) {
      setMemory(null);
      return;
    }
    try {
      const row = await getConversationMemory(id);
      setMemory(row && row.content ? row : null);
    } catch {
      setMemory(null);
    }
  };

  const applyConversationId = (id, { syncUrl = true } = {}) => {
    setConversationId(id);
    persistConversationId(id);
    if (syncUrl) {
      if (id) setSearchParams({ c: id }, { replace: true });
      else setSearchParams({}, { replace: true });
    }
  };

  const openConversation = async (conversation) => {
    setSessionError("");
    applyConversationId(conversation.id);
    setConversationTitle(conversation.title || "新对话");
    setMessages(await getMessages(conversation.id));
    await loadMemory(conversation.id);
  };

  useEffect(() => {
    refreshConversations()
      .then(async (rows) => {
        if (restoredRef.current) return;
        restoredRef.current = true;
        const fromUrl = searchParams.get("c");
        const fromStore = localStorage.getItem(STORAGE_KEY);
        const wanted = fromUrl || fromStore;
        if (!wanted) return;
        const match = rows.find((item) => item.id === wanted);
        if (match) {
          await openConversation(match);
          return;
        }
        setSessionError("无法恢复该会话（不存在或无权限），已开始新对话。");
        persistConversationId(null);
        setSearchParams({}, { replace: true });
      })
      .catch(console.error);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    listChatTools()
      .then(setTools)
      .catch(() => setTools([]));
  }, [hasPermission]);

  useEffect(() => {
    textareaRef.current?.focus();
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, loading]);

  const newConversation = async () => {
    setSessionError("");
    const conversation = await createConversation();
    const rows = await refreshConversations();
    applyConversationId(conversation.id);
    setConversationTitle(conversation.title || "新对话");
    setMessages([]);
    setMemory(null);
    setAttachment(null);
    setActiveTool("");
    setConversations(rows);
    setEditingTitleId(null);
    setEditingTitleSurface(null);
  };

  const beginRename = (conversation, surface = "list") => {
    editingTitleIdRef.current = conversation.id;
    const draft = conversation.title || "新对话";
    editingTitleDraftRef.current = draft;
    setEditingTitleId(conversation.id);
    setEditingTitleDraft(draft);
    setEditingTitleSurface(surface);
  };

  const cancelRename = () => {
    editingTitleIdRef.current = null;
    editingTitleDraftRef.current = "";
    setEditingTitleId(null);
    setEditingTitleSurface(null);
  };

  const commitRename = async () => {
    const id = editingTitleIdRef.current;
    if (!id) return;
    const next = (editingTitleDraftRef.current || "").trim();
    if (!next) {
      setSessionError("标题不能为空");
      cancelRename();
      return;
    }
    const prev =
      conversations.find((c) => c.id === id)?.title ||
      (id === conversationId ? conversationTitle : "");
    if (next === prev) {
      cancelRename();
      return;
    }
    editingTitleIdRef.current = null;
    setEditingTitleId(null);
    setEditingTitleSurface(null);
    try {
      const updated = await updateConversationTitle(id, next);
      setConversations((rows) =>
        rows.map((c) => (c.id === id ? { ...c, ...updated } : c)),
      );
      if (id === conversationId) setConversationTitle(updated.title);
      setSessionError("");
    } catch (err) {
      setSessionError(err.message || "改名失败");
    }
  };

  const onDeleteConversation = async (conversation) => {
    if (!conversation?.id) return;
    const title = conversation.title || "新对话";
    if (!window.confirm(`确认删除「${title}」？删除后不可恢复。`)) return;
    try {
      await deleteConversation(conversation.id);
      setConversations((rows) => rows.filter((c) => c.id !== conversation.id));
      if (conversation.id === conversationId) {
        applyConversationId(null);
        setConversationTitle("新对话");
        setMessages([]);
        setMemory(null);
        setAttachment(null);
      }
      setSessionError("");
    } catch (err) {
      setSessionError(err.message || "删除失败");
    }
  };

  const onPickAttachment = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const lower = (file.name || "").toLowerCase();
    if (!lower.endsWith(".xlsx") && !lower.endsWith(".xls") && !lower.endsWith(".pdf")) {
      setSessionError("仅支持 Excel（.xlsx）或由该工作簿导出的 PDF");
      return;
    }
    setAttachBusy(true);
    setSessionError("");
    try {
      const meta = await uploadChatAttachment(file);
      setAttachment(meta);
    } catch (err) {
      setSessionError(err.message || "附件上传失败");
    } finally {
      setAttachBusy(false);
    }
  };

  const runToolAction = async (action, payload = {}) => {
    if (!conversationId || loading) return;
    setLoading(true);
    try {
      await chatToolAction({ conversationId, action, payload });
      setMessages(await getMessages(conversationId));
    } catch (err) {
      setSessionError(err.message || "工具动作失败");
    } finally {
      setLoading(false);
    }
  };

  const send = async (rawText) => {
    const text = (rawText ?? input).trim();
    if ((!text && !attachment) || loading) return;
    const outbound = text || (attachment ? `请处理附件 ${attachment.filename}` : "");
    setInput("");
    setLoading(true);
    setSessionError("");

    let currentId = conversationId;
    let currentTitle = conversationTitle;
    const attachMeta = attachment;
    const optimisticMessages = [
      ...messages,
      {
        role: "user",
        content: attachMeta ? `${outbound}\n[附件] ${attachMeta.filename}` : outbound,
      },
      { role: "assistant", content: "", streaming: true },
    ];
    setMessages(optimisticMessages);
    setAttachment(null);

    let assembled = "";
    try {
      await streamChat({
        message: outbound,
        conversationId: currentId,
        activeTool: activeTool,
        attachmentId: attachMeta?.id || null,
        onStart: (data) => {
          currentId = data.conversation_id;
          applyConversationId(currentId);
        },
        onToken: (token) => {
          assembled += token;
          setMessages([
            ...optimisticMessages.slice(0, -1),
            { role: "assistant", content: assembled, streaming: true },
          ]);
        },
        onDone: (data) => {
          currentId = data.conversation_id;
          assembled = data.answer || assembled;
          setMessages([
            ...optimisticMessages.slice(0, -1),
            {
              role: "assistant",
              content: assembled,
              id: data.message_id,
              meta: data.card ? { tool: "staffing", card: data.card } : undefined,
              citations: data.citations || [],
            },
          ]);
        },
        onError: (error) => {
          assembled += `\n[错误] ${typeof error === "string" ? error : error?.message || error}`;
          setSessionError(assembled.includes("[错误]") ? assembled.replace(/^\n?\[错误\]\s*/, "") : "对话失败");
        },
      });
    } catch (error) {
      assembled += `\n[错误] ${error.message}`;
      setSessionError(error.message || "对话失败");
      if (error.status === 404) {
        setSessionError("会话不存在或无权限，请新建对话。");
        applyConversationId(null);
      }
    }

    applyConversationId(currentId);
    setLoading(false);
    const rows = await refreshConversations();
    const active = rows.find((item) => item.id === currentId);
    if (active) currentTitle = active.title;
    setConversationTitle(currentTitle);
    if (currentId) {
      try {
        setMessages(await getMessages(currentId));
        await loadMemory(currentId);
      } catch (err) {
        // Keep streamed content if reload fails
        if (!assembled) setSessionError(err.message || "加载消息失败");
      }
    }
  };

  const feedback = async (message, rating) => {
    if (!message.id) return;
    try {
      await submitFeedback({ messageId: message.id, rating, comment: "" });
    } catch (error) {
      console.error(error);
    }
  };

  const empty = !conversationId && messages.length === 0;

  return (
    <div className="chat-layout">
      <aside className="sidebar">
        <Link to="/" className="side-link brand-link">
          <BrandLogo size={26} />
          {BRAND_PRODUCT_NAME}
        </Link>
        <button className="new-chat" onClick={newConversation}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
            <path d="M12 5v14M5 12h14" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
          </svg>
          新对话
        </button>

        <div className="side-section">最近</div>
        {memory?.content && (
          <div className="session-memory" aria-label="会话记忆">
            <div className="session-memory-title">会话记忆（压缩摘要）</div>
            <p className="session-memory-body">{memory.content}</p>
            <div className="session-memory-hint">只读 · 完整原文见下方消息</div>
          </div>
        )}
        {sessionError && <div className="session-error">{sessionError}</div>}
        <div className="conversation-list">
          {conversations.length === 0 && (
            <div className="conversation-empty">还没有历史会话</div>
          )}
          {conversations.map((conversation) => (
            <div
              key={conversation.id}
              className={`conversation-item ${conversation.id === conversationId ? "active" : ""}`}
            >
              {editingTitleId === conversation.id && editingTitleSurface === "list" ? (
                <input
                  className="conversation-title-input"
                  value={editingTitleDraft}
                  autoFocus
                  onChange={(e) => {
                    editingTitleDraftRef.current = e.target.value;
                    setEditingTitleDraft(e.target.value);
                  }}
                  onBlur={() => {
                    window.setTimeout(() => {
                      if (editingTitleIdRef.current === conversation.id) commitRename();
                    }, 120);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      commitRename();
                    }
                    if (e.key === "Escape") {
                      e.preventDefault();
                      cancelRename();
                    }
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              ) : (
                <>
                  <button
                    type="button"
                    className="conversation-item-btn"
                    onClick={() => openConversation(conversation)}
                    title={conversation.title || "新对话"}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden>
                      <path
                        d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                    <span>{conversation.title || "新对话"}</span>
                  </button>
                  <button
                    type="button"
                    className="conversation-rename-btn"
                    title="改名"
                    aria-label="改名"
                    onClick={(e) => {
                      e.stopPropagation();
                      beginRename(conversation, "list");
                    }}
                  >
                    改名
                  </button>
                  <button
                    type="button"
                    className="conversation-delete-btn"
                    title="删除"
                    aria-label="删除"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteConversation(conversation);
                    }}
                  >
                    删除
                  </button>
                </>
              )}
            </div>
          ))}
        </div>

        <div className="sidebar-footer">
          <Link to="/documents" className="side-link small">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
              <path
                d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
            </svg>
            文档管理
          </Link>
        </div>
      </aside>

      <main className="chat-main">
        {conversationId && (
          <header className="chat-header">
            {editingTitleId === conversationId && editingTitleSurface === "header" ? (
              <input
                className="chat-title-input"
                value={editingTitleDraft}
                autoFocus
                onChange={(e) => {
                  editingTitleDraftRef.current = e.target.value;
                  setEditingTitleDraft(e.target.value);
                }}
                onBlur={() => {
                  window.setTimeout(() => {
                    if (editingTitleIdRef.current === conversationId) commitRename();
                  }, 120);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    commitRename();
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    cancelRename();
                  }
                }}
              />
            ) : (
              <div className="chat-title-row">
                <span className="chat-title">
                  {editingTitleId === conversationId
                    ? editingTitleDraft
                    : conversationTitle || "新对话"}
                </span>
                <button
                  type="button"
                  className="chat-rename-btn"
                  onClick={() =>
                    beginRename({ id: conversationId, title: conversationTitle }, "header")
                  }
                >
                  改名
                </button>
              </div>
            )}
          </header>
        )}

        {empty ? (
          <section className="welcome">
            <div className="welcome-logo">
              <BrandLogo size={52} />
            </div>
            <h1>你好，我是你的企业知识库助手</h1>
            <p>上传产品手册与制度文档后，我可以基于文档回答你的问题，并支持连续追问。</p>
            <div className="suggestions">
              {SUGGESTIONS.map((suggestion) => (
                <button key={suggestion} onClick={() => send(suggestion)}>
                  {suggestion}
                </button>
              ))}
            </div>
          </section>
        ) : (
          <section className="messages">
            <div className="message-column">
              {messages.map((message, index) => (
                <div className={`message ${message.role}`} key={index}>
                  {message.role === "assistant" && (
                    <div className="avatar" aria-hidden>
                      知
                    </div>
                  )}
                  <div className="message-body">
                    {message.role === "assistant" ? (
                      <>
                        <RichText text={message.content || (message.streaming ? "正在思考…" : "")} />
                        {message.meta?.card?.type === "staffing_batch" ? (
                          <StaffingBatchCard
                            card={message.meta.card}
                            disabled={loading}
                            onConfirm={(action, payload) => runToolAction(action, payload)}
                          />
                        ) : null}
                        {message.meta?.card?.type === "staffing_summary" ? (
                          <LiveStaffingSummary card={message.meta.card} />
                        ) : null}
                        {message.meta?.card?.type === "leave_ledger_job" ? (
                          <LeaveLedgerJobCard
                            card={message.meta.card}
                            disabled={loading}
                            onAction={(action, payload) => runToolAction(action, payload)}
                          />
                        ) : null}
                        {message.citations?.length > 0 && (
                          <div className="citations">
                            {message.citations.map((citation) => (
                              <span className="citation-chip" key={citation.chunk_id}>
                                📄 {citation.document_title}
                                {citation.page > 0
                                  ? ` · 第 ${citation.page} 页`
                                  : citation.section
                                    ? ` · ${citation.section}`
                                    : ""}
                                {citation.images?.length > 0 && (
                                  <span className="citation-images">
                                    {citation.images.map((image) => (
                                      <a
                                        key={image.image_id}
                                        href={image.url}
                                        target="_blank"
                                        rel="noreferrer"
                                        title={image.caption || "查看原图"}
                                        onClick={(event) => {
                                          event.preventDefault();
                                          const gallery = galleryFor(message);
                                          setLightbox({
                                            images: gallery,
                                            index: gallery.findIndex((item) => item.image_id === image.image_id),
                                          });
                                        }}
                                      >
                                        <img
                                          src={`${image.url}?w=200`}
                                          loading="lazy"
                                          alt={image.caption || "引用图片"}
                                          style={{ width: 64, height: 64, objectFit: "cover", borderRadius: 6, marginLeft: 6, verticalAlign: "middle" }}
                                          onError={(event) => {
                                            event.currentTarget.parentElement.style.display = "none";
                                          }}
                                        />
                                      </a>
                                    ))}
                                  </span>
                                )}
                              </span>
                            ))}
                          </div>
                        )}
                        {message.id && !message.streaming && (
                          <div className="feedback">
                            <button title="有帮助" onClick={() => feedback(message, "up")}>
                              👍
                            </button>
                            <button title="没帮助" onClick={() => feedback(message, "down")}>
                              👎
                            </button>
                          </div>
                        )}
                      </>
                    ) : (
                      <div className="user-bubble">
                        <RichText text={message.content} />
                      </div>
                    )}
                  </div>
                </div>
              ))}
              <div ref={bottomRef} />
            </div>
          </section>
        )}

        <footer className="composer-wrap">
          {sessionError ? <div className="composer-error">{sessionError}</div> : null}
          {attachment ? (
            <div className="composer-attach-chip">
              已附加：{attachment.filename}
              <button type="button" onClick={() => setAttachment(null)}>
                移除
              </button>
            </div>
          ) : null}
          <div className="composer">
            <textarea
              ref={textareaRef}
              rows={1}
              value={input}
              placeholder="问点想问的，或附上项目日报让我帮你做人员投入…"
              onChange={(event) => setInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  send();
                }
              }}
            />
            <div className="composer-tools">
              <label className="composer-icon-btn" title="上传 Excel（.xlsx）或由其导出的 PDF" aria-label="上传 Excel 或 PDF">
                <input
                  type="file"
                  accept=".xlsx,.xls,.pdf"
                  hidden
                  disabled={attachBusy || loading}
                  onChange={onPickAttachment}
                />
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                  <path
                    d="M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </label>
              {tools.length ? (
                <div className="tool-menu">
                  <button
                    type="button"
                    className={`composer-icon-btn${activeTool ? " active" : ""}`}
                    title="选择工具"
                    onClick={() => setToolMenuOpen((v) => !v)}
                  >
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                      <path
                        d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      />
                    </svg>
                  </button>
                  {toolMenuOpen ? (
                    <div className="tool-menu-dropdown">
                      <button
                        type="button"
                        className={!activeTool ? "selected" : ""}
                        onClick={() => {
                          setActiveTool("");
                          setToolMenuOpen(false);
                        }}
                      >
                        不使用工具
                      </button>
                      {tools.map((t) => (
                        <button
                          key={t.id}
                          type="button"
                          className={activeTool === t.id ? "selected" : ""}
                          onClick={() => {
                            setActiveTool(t.id);
                            setToolMenuOpen(false);
                          }}
                        >
                          {t.label}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
              <button
                className="send"
                onClick={() => send()}
                disabled={(!input.trim() && !attachment) || loading}
                title="发送"
              >
                {loading ? (
                  <span className="spinner" />
                ) : (
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden>
                    <path
                      d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                )}
              </button>
            </div>
          </div>
          <div className="composer-hint">
            {activeTool
              ? `当前工具：${tools.find((t) => t.id === activeTool)?.label || activeTool}`
              : "回答基于已上传文档；也可选工具或附上项目日报做人员投入"}
          </div>
        </footer>
      </main>
      {lightbox && lightbox.images[lightbox.index] && (
        <div
          role="dialog"
          aria-modal="true"
          onClick={() => setLightbox(null)}
          style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.82)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", zIndex: 1000, padding: 16 }}
        >
          <img
            src={`${lightbox.images[lightbox.index].url}?w=800`}
            alt={lightbox.images[lightbox.index].caption || "引用图片"}
            onClick={(event) => event.stopPropagation()}
            style={{ maxWidth: "90vw", maxHeight: "78vh", objectFit: "contain", borderRadius: 8, background: "#fff" }}
          />
          <div onClick={(event) => event.stopPropagation()} style={{ color: "#fff", marginTop: 12, fontSize: 13 }}>
            {lightbox.images[lightbox.index].caption || "引用图片"}
            {lightbox.images[lightbox.index].page > 0 ? ` · 第 ${lightbox.images[lightbox.index].page} 页` : ""}
            {" · "}
            <a href={lightbox.images[lightbox.index].url} target="_blank" rel="noreferrer" style={{ color: "#8ab4ff" }}>
              查看原图
            </a>
          </div>
          {lightbox.images.length > 1 && (
            <div onClick={(event) => event.stopPropagation()} style={{ display: "flex", gap: 12, marginTop: 12 }}>
              <button onClick={() => setLightbox((prev) => ({ ...prev, index: (prev.index - 1 + prev.images.length) % prev.images.length }))}>
                上一张
              </button>
              <button onClick={() => setLightbox((prev) => ({ ...prev, index: (prev.index + 1) % prev.images.length }))}>下一张</button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
