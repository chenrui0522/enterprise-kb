import { useEffect, useMemo, useState } from "react";
import {
  confirmStaffingImport,
  exportStaffingXlsx,
  getStaffingSummary,
  listMyStaffingProjects,
  listStaffingFacts,
  mergeStaffingNames,
  repairStaffingRosterNames,
  reviewStaffingImport,
  uploadStaffingImport,
  voidStaffing,
} from "../api.js";
import { useAuth } from "../auth.jsx";
import StaffingSummaryPanel from "../components/StaffingSummaryPanel.jsx";

const KIND_LABEL = {
  internal_formal: "正式我司",
  internal_contract: "机电服务处",
};

export default function StaffingPage() {
  const { user, hasPermission } = useAuth();
  const canRead = Boolean(user?.can_staffing);
  const canWrite = canRead && hasPermission("staffing:write");

  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [batch, setBatch] = useState(null);
  const [summary, setSummary] = useState(null);
  const [facts, setFacts] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [mergeBusy, setMergeBusy] = useState(false);
  const [repairBusy, setRepairBusy] = useState(false);
  const [selectedPeople, setSelectedPeople] = useState([]);
  const [collisionChoices, setCollisionChoices] = useState({});
  const [rosterChoices, setRosterChoices] = useState({});

  useEffect(() => {
    if (!canRead) return;
    listMyStaffingProjects()
      .then((rows) => {
        setProjects(rows);
        if (rows.length && !projectId) setProjectId(rows[0].id);
      })
      .catch((e) => setError(e.message));
  }, [canRead]);

  async function refreshProject(pid) {
    if (!pid) return;
    const [s, f] = await Promise.all([getStaffingSummary(pid), listStaffingFacts(pid)]);
    setSummary(s);
    setFacts(f);
  }

  useEffect(() => {
    if (projectId) {
      refreshProject(projectId).catch((e) => setError(e.message));
    }
  }, [projectId]);

  const collisions = useMemo(() => {
    if (!batch) return [];
    return (batch.warnings || []).filter((w) => w.code === "name_kind_collision");
  }, [batch]);

  const openWarnings = useMemo(() => {
    if (!batch) return [];
    const resolved = batch.resolved_warnings || {};
    return (batch.warnings || []).filter((w) => {
      if (["project_unmatched", "project_ambiguous"].includes(w.code) && batch.project_id) {
        return false;
      }
      if (w.code === "roster_name_corrected") return false;
      if (w.code === "roster_unavailable") return true;
      if (w.code === "name_kind_collision") {
        const name = w.detail?.person_name;
        const entry = resolved.name_kind_collision?.[name] || collisionChoices[name];
        if (entry?.action === "split") return false;
        if (entry?.action === "merge" && entry?.keep_kind) return false;
        return true;
      }
      if (w.code === "roster_name_unresolved") {
        const token = w.detail?.token;
        const entry = resolved.roster_name_unresolved?.[token] || rosterChoices[token];
        if (entry?.action === "discard") return false;
        if (
          (entry?.action === "select_roster_name" || entry?.action === "rename") &&
          entry?.name
        ) {
          return false;
        }
        return true;
      }
      return !resolved[w.code];
    });
  }, [batch, collisionChoices, rosterChoices]);

  const rosterUnresolved = useMemo(() => {
    if (!batch) return [];
    return (batch.warnings || []).filter((w) => w.code === "roster_name_unresolved");
  }, [batch]);

  const rosterUnavailable = useMemo(() => {
    if (!batch) return false;
    return (batch.warnings || []).some((w) => w.code === "roster_unavailable");
  }, [batch]);

  function syncCollisionDefaults(b) {
    const init = {};
    for (const w of b.warnings || []) {
      if (w.code === "name_kind_collision" && w.detail?.person_name) {
        init[w.detail.person_name] = { action: "split" };
      }
    }
    setCollisionChoices(init);
    setRosterChoices({});
  }

  async function onUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    const lower = (file.name || "").toLowerCase();
    if (!lower.endsWith(".xlsx") && !lower.endsWith(".pdf")) {
      setError("仅支持 Excel（.xlsx）或由该工作簿导出的 PDF");
      e.target.value = "";
      return;
    }
    setBusy(true);
    setError("");
    try {
      const b = await uploadStaffingImport(file);
      setBatch(b);
      syncCollisionDefaults(b);
      if (b.project_id) setProjectId(b.project_id);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
      e.target.value = "";
    }
  }

  function buildResolutions(b) {
    const resolutions = {};
    const skipAck = new Set([
      "name_kind_collision",
      "roster_name_unresolved",
      "roster_unavailable",
      "roster_name_corrected",
    ]);
    for (const w of b.warnings || []) {
      if (!w.code || skipAck.has(w.code)) continue;
      resolutions[w.code] = "acknowledged";
    }
    if (Object.keys(collisionChoices).length) {
      resolutions.name_kind_collision = collisionChoices;
    }
    if (Object.keys(rosterChoices).length) {
      resolutions.roster_name_unresolved = rosterChoices;
    }
    return resolutions;
  }

  async function onResolveAll() {
    if (!batch) return;
    setBusy(true);
    setError("");
    try {
      const body = { resolutions: buildResolutions(batch) };
      if (!batch.project_id && projectId) body.project_id = projectId;
      const b = await reviewStaffingImport(batch.id, body);
      setBatch(b);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onMergeNameSplit(shortName, longName) {
    if (!batch) return;
    setBusy(true);
    setError("");
    try {
      const body = {
        resolutions: buildResolutions(batch),
        person_renames: { [shortName]: longName },
      };
      if (!batch.project_id && projectId) body.project_id = projectId;
      const b = await reviewStaffingImport(batch.id, body);
      setBatch(b);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onConfirm() {
    if (!batch) return;
    setBusy(true);
    setError("");
    try {
      let b = batch;
      if (b.status === "needs_review") {
        b = await reviewStaffingImport(b.id, {
          project_id: projectId || b.project_id,
          resolutions: buildResolutions(b),
        });
      }
      b = await confirmStaffingImport(b.id);
      setBatch(b);
      if (b.project_id) {
        setProjectId(b.project_id);
        await refreshProject(b.project_id);
      }
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  async function onVoidPeople() {
    if (!projectId || !selectedPeople.length) return;
    setBusy(true);
    try {
      await voidStaffing(projectId, { scope: "person", person_names: selectedPeople });
      setSelectedPeople([]);
      await refreshProject(projectId);
    } catch (err) {
      setError(err.message || String(err));
    } finally {
      setBusy(false);
    }
  }

  if (!canRead) {
    return (
      <main className="panel">
        <p className="muted">无人员投入读取权限</p>
      </main>
    );
  }

  return (
    <main className="panel staffing-page">
      <h1>人员投入</h1>
      <p className="muted">
        仅统计公司内部员工在场天数（正式我司 / 机电服务处）。同名双身份须人工裁定；导入后可导出
        Excel。
      </p>

      {error ? <p className="error">{error}</p> : null}

      <section className="stack-gap">
        <label>
          当前项目{" "}
          <select value={projectId} onChange={(e) => setProjectId(e.target.value)}>
            <option value="">选择项目</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} · {p.name}
              </option>
            ))}
          </select>
        </label>

        {canWrite ? (
          <label className="file-upload">
            上传项目日报（.xlsx 或由其导出的 PDF）
            <input
              type="file"
              accept=".xlsx,.pdf,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/pdf"
              onChange={onUpload}
              disabled={busy}
            />
          </label>
        ) : null}
      </section>

      {batch ? (
        <section className="stack-gap card-block">
          <h2>导入批次</h2>
          <p>
            文件：{batch.filename} · 状态：{batch.status}
            {batch.project_id ? ` · 项目已绑定` : " · 尚未绑定项目"}
          </p>
          {collisions.length ? (
            <div className="tool-card-collisions">
              <h3>同名双身份</h3>
              {collisions.map((w) => {
                const name = w.detail?.person_name;
                const choice = collisionChoices[name] || { action: "split" };
                return (
                  <div className="collision-row" key={name}>
                    <strong>{name}</strong>
                    <p className="muted">{w.message}</p>
                    <div className="collision-actions">
                      <label>
                        <input
                          type="radio"
                          name={`pg-col-${name}`}
                          checked={choice.action === "split"}
                          onChange={() =>
                            setCollisionChoices((prev) => ({
                              ...prev,
                              [name]: { action: "split" },
                            }))
                          }
                        />
                        不同人（分列）
                      </label>
                      <label>
                        <input
                          type="radio"
                          name={`pg-col-${name}`}
                          checked={choice.action === "merge"}
                          onChange={() =>
                            setCollisionChoices((prev) => ({
                              ...prev,
                              [name]: {
                                action: "merge",
                                keep_kind: prev[name]?.keep_kind || "internal_formal",
                              },
                            }))
                          }
                        />
                        同一人，保留
                      </label>
                      {choice.action === "merge" ? (
                        <select
                          value={choice.keep_kind || "internal_formal"}
                          onChange={(e) =>
                            setCollisionChoices((prev) => ({
                              ...prev,
                              [name]: { action: "merge", keep_kind: e.target.value },
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
            <div className="tool-card-collisions">
              <h3>花名册不可用</h3>
              <p className="muted">
                请配置人员信息表（环境变量 KB_STAFFING_ROSTER_PATH，默认
                ./data/staffing_roster.xlsx）后重新导入。无法在缺少花名册时确认入库。
              </p>
            </div>
          ) : null}
          {rosterUnresolved.length ? (
            <div className="tool-card-collisions">
              <h3>花名册无法确认的姓名</h3>
              {rosterUnresolved.map((w) => {
                const token = w.detail?.token;
                const candidates = w.detail?.candidates || [];
                const choice = rosterChoices[token] || {};
                return (
                  <div className="collision-row" key={token}>
                    <strong>{token}</strong>
                    <p className="muted">{w.message}</p>
                    <div className="collision-actions">
                      {candidates.length ? (
                        <label>
                          选定花名册
                          <select
                            value={
                              choice.action === "select_roster_name" ? choice.name || "" : ""
                            }
                            onChange={(e) => {
                              const name = e.target.value;
                              if (!name) return;
                              setRosterChoices((prev) => ({
                                ...prev,
                                [token]: { action: "select_roster_name", name },
                              }));
                            }}
                          >
                            <option value="">请选择</option>
                            {candidates.map((c) => (
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
                          placeholder="手工姓名"
                          value={choice.action === "rename" ? choice.name || "" : ""}
                          onChange={(e) =>
                            setRosterChoices((prev) => ({
                              ...prev,
                              [token]: { action: "rename", name: e.target.value },
                            }))
                          }
                        />
                      </label>
                      <label>
                        <input
                          type="radio"
                          name={`roster-discard-${token}`}
                          checked={choice.action === "discard"}
                          onChange={() =>
                            setRosterChoices((prev) => ({
                              ...prev,
                              [token]: { action: "discard" },
                            }))
                          }
                        />
                        丢弃（当日不计）
                      </label>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
          {openWarnings.length ? (
            <div>
              <h3>待复核告警（{openWarnings.length}）</h3>
              <ul>
                {openWarnings
                  .filter(
                    (w) =>
                      w.code !== "name_kind_collision" &&
                      w.code !== "roster_name_unresolved" &&
                      w.code !== "roster_unavailable",
                  )
                  .slice(0, 30)
                  .map((w, i) => (
                    <li key={`${w.code}-${i}`}>
                      <code>{w.code}</code> {w.message}
                      {w.row ? ` · 行 ${w.row}` : ""}
                      {w.code === "suspected_name_split" &&
                      w.detail?.short_name &&
                      w.detail?.long_name &&
                      canWrite ? (
                        <div className="collision-actions">
                          <button
                            type="button"
                            disabled={busy}
                            onClick={() =>
                              onMergeNameSplit(w.detail.short_name, w.detail.long_name)
                            }
                          >
                            合并为「{w.detail.long_name}」
                          </button>
                        </div>
                      ) : null}
                    </li>
                  ))}
              </ul>
              {canWrite ? (
                <button type="button" onClick={onResolveAll} disabled={busy}>
                  确认已知晓上述告警
                </button>
              ) : null}
            </div>
          ) : (
            <p className="muted">无未决议告警（或已确认知晓）</p>
          )}
          {canWrite ? (
            <button
              type="button"
              onClick={onConfirm}
              disabled={busy || batch.status === "confirmed" || openWarnings.length > 0}
            >
              确认入库
            </button>
          ) : null}
        </section>
      ) : null}

      {summary ? (
        <section className="stack-gap">
          <StaffingSummaryPanel
            summary={summary}
            mergeBusy={mergeBusy}
            repairBusy={repairBusy}
            onMergeNames={
              canWrite && projectId
                ? async (fromName, toName) => {
                    setMergeBusy(true);
                    setError("");
                    try {
                      await mergeStaffingNames(projectId, fromName, toName);
                      await refreshProject(projectId);
                    } catch (err) {
                      setError(err.message || "合并失败");
                    } finally {
                      setMergeBusy(false);
                    }
                  }
                : undefined
            }
            onRepairRosterNames={
              canWrite && projectId
                ? async () => {
                    setRepairBusy(true);
                    setError("");
                    try {
                      const result = await repairStaffingRosterNames(projectId);
                      await refreshProject(projectId);
                      if (result.unresolved_count) {
                        setError(
                          `已自动纠正 ${result.applied_count} 个姓名；仍有 ${result.unresolved_count} 个需人工裁定`,
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
              projectId
                ? async () => {
                    try {
                      await exportStaffingXlsx(projectId);
                    } catch (err) {
                      setError(err.message || "导出失败");
                    }
                  }
                : undefined
            }
          />
          {canWrite ? (
            <div>
              <table className="data-table">
                <thead>
                  <tr>
                    <th />
                    <th>姓名</th>
                    <th>身份</th>
                    <th>天数</th>
                    <th>进场次数</th>
                    <th>工期段</th>
                  </tr>
                </thead>
                <tbody>
                  {summary.people.map((p) => {
                    const stints =
                      Array.isArray(p.stints) && p.stints.length
                        ? p.stints
                        : [];
                    const stintCount = stints.length || Number(p.stint_count) || 0;
                    return (
                    <tr key={`${p.person_name}-${p.person_kind}`}>
                      <td>
                        <input
                          type="checkbox"
                          checked={selectedPeople.includes(p.person_name)}
                          onChange={(e) => {
                            setSelectedPeople((prev) =>
                              e.target.checked
                                ? [...prev, p.person_name]
                                : prev.filter((n) => n !== p.person_name),
                            );
                          }}
                        />
                      </td>
                      <td>{p.person_name}</td>
                      <td>{p.person_kind_label || KIND_LABEL[p.person_kind] || p.person_kind}</td>
                      <td>{p.days_on_site}</td>
                      <td>{stintCount}</td>
                      <td>
                        {stints
                          .map(
                            (s) =>
                              `${s.index}: ${(s.entry_date || "").slice(5)}~${(s.exit_date || "").slice(5)}`,
                          )
                          .join("; ") || "—"}
                      </td>
                    </tr>
                    );
                  })}                </tbody>
              </table>
              {selectedPeople.length ? (
                <button type="button" onClick={onVoidPeople} disabled={busy}>
                  作废所选人员在本项目全部在场日
                </button>
              ) : null}
            </div>
          ) : null}
        </section>
      ) : null}

      {facts.length ? (
        <section className="stack-gap">
          <h2>明细（有效）</h2>
          <table className="data-table">
            <thead>
              <tr>
                <th>日期</th>
                <th>姓名</th>
                <th>身份</th>
                <th>当前阶段</th>
              </tr>
            </thead>
            <tbody>
              {facts.slice(0, 200).map((f) => (
                <tr key={f.id}>
                  <td>{f.work_date}</td>
                  <td>{f.person_name}</td>
                  <td>{KIND_LABEL[f.person_kind] || f.person_kind}</td>
                  <td>{f.stage || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {facts.length > 200 ? <p className="muted">仅显示前 200 条</p> : null}
        </section>
      ) : null}
    </main>
  );
}
