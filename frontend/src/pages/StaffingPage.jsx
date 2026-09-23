import { useEffect, useMemo, useState } from "react";
import {
  confirmStaffingImport,
  exportStaffingXlsx,
  getStaffingSummary,
  listMyStaffingProjects,
  listStaffingFacts,
  reviewStaffingImport,
  uploadStaffingImport,
  voidStaffing,
} from "../api.js";
import { useAuth } from "../auth.jsx";
import StaffingSummaryPanel from "../components/StaffingSummaryPanel.jsx";

const KIND_LABEL = {
  internal_formal: "正式我司",
  internal_contract: "我司·外包性质",
};

export default function StaffingPage() {
  const { hasPermission } = useAuth();
  const canWrite = hasPermission("staffing:write");
  const canRead = hasPermission("staffing:read");

  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState("");
  const [batch, setBatch] = useState(null);
  const [summary, setSummary] = useState(null);
  const [facts, setFacts] = useState([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedPeople, setSelectedPeople] = useState([]);
  const [collisionChoices, setCollisionChoices] = useState({});

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
      if (w.code === "name_kind_collision") {
        const name = w.detail?.person_name;
        const entry = resolved.name_kind_collision?.[name] || collisionChoices[name];
        if (entry?.action === "split") return false;
        if (entry?.action === "merge" && entry?.keep_kind) return false;
        return true;
      }
      return !resolved[w.code];
    });
  }, [batch, collisionChoices]);

  function syncCollisionDefaults(b) {
    const init = {};
    for (const w of b.warnings || []) {
      if (w.code === "name_kind_collision" && w.detail?.person_name) {
        init[w.detail.person_name] = { action: "split" };
      }
    }
    setCollisionChoices(init);
  }

  async function onUpload(e) {
    const file = e.target.files?.[0];
    if (!file) return;
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
    for (const w of b.warnings || []) {
      if (!w.code || w.code === "name_kind_collision") continue;
      resolutions[w.code] = "acknowledged";
    }
    if (Object.keys(collisionChoices).length) {
      resolutions.name_kind_collision = collisionChoices;
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
        仅统计公司内部员工在场天数（正式我司 / 我司·外包性质）。同名双身份须人工裁定；导入后可导出
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
            上传项目日报（.xlsx）
            <input
              type="file"
              accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
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
                          <option value="internal_contract">我司·外包性质</option>
                        </select>
                      ) : null}
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
                  .filter((w) => w.code !== "name_kind_collision")
                  .slice(0, 30)
                  .map((w, i) => (
                    <li key={`${w.code}-${i}`}>
                      <code>{w.code}</code> {w.message}
                      {w.row ? ` · 行 ${w.row}` : ""}
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
              </tr>
            </thead>
            <tbody>
              {facts.slice(0, 200).map((f) => (
                <tr key={f.id}>
                  <td>{f.work_date}</td>
                  <td>{f.person_name}</td>
                  <td>{KIND_LABEL[f.person_kind] || f.person_kind}</td>
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
