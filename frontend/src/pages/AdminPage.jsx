import { useCallback, useEffect, useMemo, useState } from "react";
import { Navigate, useSearchParams } from "react-router-dom";
import {
  addProjectMember,
  bindUserPosition,
  createOrgUnit,
  createPosition,
  createProject,
  createUser,
  listOrgUnits,
  listPositions,
  listProjectMembers,
  listProjects,
  listUsers,
  listAuditEvents,
  removeProjectMember,
  setEstablishment,
  unbindUserPosition,
  updateUserClearance,
} from "../api.js";
import { useAuth } from "../auth.jsx";
import {
  CLEARANCE_OPTIONS,
  ORG_TYPE_OPTIONS,
  SITE_OPTIONS,
  clearanceLabel,
  orderOrgUnitsTree,
  orgOptionLabel,
  orgTypeLabel,
  siteLabel,
} from "../identityLabels.js";

const DOMAINS = [
  "software",
  "electrical",
  "mechanical",
  "procurement",
  "operations",
  "finance",
  "sales",
];
const ROLE_OPTIONS = ["admin", "editor", "reader", "auditor"];

const TABS = [
  { id: "org", label: "组织", perm: "orgs:manage" },
  { id: "positions", label: "岗位", perm: "orgs:manage" },
  { id: "users", label: "用户与绑岗", perm: "users:manage" },
  { id: "projects", label: "项目授权", perm: "projects:manage" },
  { id: "audit", label: "审计", perm: "audit:read" },
];

function Field({ label, children, required }) {
  return (
    <label className="admin-field">
      <span>
        {label}
        {required ? <em className="req"> *</em> : null}
      </span>
      {children}
    </label>
  );
}

function Message({ text, tone = "info" }) {
  if (!text) return null;
  return <p className={`admin-msg admin-msg-${tone}`}>{text}</p>;
}

export default function AdminPage() {
  const { hasPermission } = useAuth();
  const [searchParams] = useSearchParams();
  const canAny = TABS.some((t) => hasPermission(t.perm));
  const visibleTabs = TABS.filter((t) => hasPermission(t.perm));
  const requestedTab = searchParams.get("tab");
  const initialTab =
    (requestedTab && visibleTabs.find((t) => t.id === requestedTab)?.id) ||
    visibleTabs[0]?.id ||
    "org";
  const [tab, setTab] = useState(initialTab);
  const [message, setMessage] = useState("");
  const [tone, setTone] = useState("info");

  const [orgUnits, setOrgUnits] = useState([]);
  const [positions, setPositions] = useState([]);
  const [users, setUsers] = useState([]);
  const [projects, setProjects] = useState([]);

  const flash = (text, nextTone = "info") => {
    setMessage(text);
    setTone(nextTone);
  };

  const reload = useCallback(async () => {
    const tasks = [];
    if (hasPermission("orgs:manage") || hasPermission("users:manage")) {
      tasks.push(listOrgUnits().then(setOrgUnits));
      tasks.push(listPositions().then(setPositions));
    }
    if (hasPermission("users:manage")) {
      tasks.push(listUsers().then(setUsers));
    }
    if (hasPermission("projects:manage")) {
      tasks.push(listProjects().then(setProjects));
    }
    await Promise.all(tasks);
  }, [hasPermission]);

  useEffect(() => {
    if (!canAny) return;
    reload().catch((err) => flash(err.message, "error"));
  }, [canAny, reload]);

  useEffect(() => {
    if (requestedTab && visibleTabs.find((t) => t.id === requestedTab)) {
      setTab(requestedTab);
      return;
    }
    if (!visibleTabs.find((t) => t.id === tab) && visibleTabs[0]) {
      setTab(visibleTabs[0].id);
    }
  }, [tab, visibleTabs, requestedTab]);

  if (!canAny) {
    return <Navigate to="/" replace />;
  }

  return (
    <main className="admin-page">
      <header className="admin-hero">
        <h1>组织与权限管理</h1>
        <p className="muted">
          组织树对齐企业微信通讯录（总经理办 + 八中心 + 泰国公司及下属部/组）。太原/朔州/苏州是人身上的地点，不是组织层；岗位视野仅本级。
        </p>
      </header>

      <nav className="admin-tabs">
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            type="button"
            className={tab === t.id ? "active" : ""}
            onClick={() => {
              setTab(t.id);
              setMessage("");
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <Message text={message} tone={tone} />

      {tab === "org" ? (
        <OrgPanel
          orgUnits={orgUnits}
          onDone={async (msg) => {
            flash(msg, "ok");
            await reload();
          }}
          onError={(err) => flash(err.message, "error")}
        />
      ) : null}
      {tab === "positions" ? (
        <PositionsPanel
          orgUnits={orgUnits}
          positions={positions}
          onDone={async (msg) => {
            flash(msg, "ok");
            await reload();
          }}
          onError={(err) => flash(err.message, "error")}
        />
      ) : null}
      {tab === "users" ? (
        <UsersPanel
          orgUnits={orgUnits}
          positions={positions}
          users={users}
          onDone={async (msg) => {
            flash(msg, "ok");
            await reload();
          }}
          onError={(err) => flash(err.message, "error")}
        />
      ) : null}
      {tab === "projects" ? (
        <ProjectsPanel
          users={users}
          projects={projects}
          canListUsers={hasPermission("users:manage")}
          onDone={async (msg) => {
            flash(msg, "ok");
            await reload();
          }}
          onError={(err) => flash(err.message, "error")}
        />
      ) : null}
      {tab === "audit" ? <AuditPanel onError={(err) => flash(err.message, "error")} /> : null}
    </main>
  );
}

function formatAuditTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  // Display in the browser's local timezone (验收环境一般为 UTC+8).
  const pad = (n) => String(n).padStart(2, "0");
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

function AuditPanel({ onError }) {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [loading, setLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAuditEvents({
        limit: 100,
        offset: 0,
        action: action.trim(),
        actor: actor.trim(),
      });
      setItems(data.items || []);
      setTotal(data.total || 0);
    } catch (err) {
      onError(err);
    } finally {
      setLoading(false);
    }
  }, [action, actor, onError]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <section className="admin-stack">
      <form
        className="admin-card"
        onSubmit={(e) => {
          e.preventDefault();
          load();
        }}
      >
        <h2>审计筛选</h2>
        <div className="admin-grid">
          <Field label="动作">
            <input value={action} onChange={(e) => setAction(e.target.value)} placeholder="如 auth.login" />
          </Field>
          <Field label="操作者">
            <input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="用户名" />
          </Field>
        </div>
        <button type="submit" disabled={loading}>
          {loading ? "查询中…" : "查询"}
        </button>
        <p className="muted">共 {total} 条（显示最近 {items.length} 条）</p>
      </form>
      <div className="admin-card">
        <h2>审计事件</h2>
        <div className="admin-table-wrap">
          <table className="admin-table">
            <thead>
              <tr>
                <th>时间</th>
                <th>操作者</th>
                <th>动作</th>
                <th>资源</th>
                <th>摘要</th>
              </tr>
            </thead>
            <tbody>
              {items.length === 0 ? (
                <tr>
                  <td colSpan={5} className="muted">
                    暂无事件
                  </td>
                </tr>
              ) : (
                items.map((item) => (
                  <tr key={item.id}>
                    <td className="admin-time">{formatAuditTime(item.created_at)}</td>
                    <td>{item.actor}</td>
                    <td>{item.action}</td>
                    <td>
                      {item.resource_type}
                      {item.resource_id ? `:${item.resource_id}` : ""}
                    </td>
                    <td>
                      <code className="admin-code">
                        {item.detail ? JSON.stringify(item.detail) : "—"}
                      </code>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

function OrgPanel({ orgUnits, onDone, onError }) {
  const [form, setForm] = useState({
    code: "",
    name: "",
    type: "dept",
    parent_id: "",
    default_site: "",
  });
  const tree = useMemo(() => orderOrgUnitsTree(orgUnits), [orgUnits]);

  const submit = async (e) => {
    e.preventDefault();
    try {
      await createOrgUnit({
        code: form.code.trim(),
        name: form.name.trim(),
        type: form.type,
        parent_id: form.parent_id || null,
        default_site: form.default_site || null,
      });
      setForm({ code: "", name: "", type: "dept", parent_id: "", default_site: "" });
      await onDone("组织节点已创建");
    } catch (err) {
      onError(err);
    }
  };

  return (
    <section className="admin-stack">
      <p className="admin-hint muted">
        种子含通讯录全量文件夹。☆太原/朔州/苏州公司仅作地点标签，不建节点；「泰国公司」为公司直属部门。挂在组上的岗位默认看不到上级部门资料。
      </p>
      <div className="admin-grid">
        <form className="admin-card" onSubmit={submit}>
          <h2>新建组织节点</h2>
          <Field label="编码" required>
            <input
              value={form.code}
              onChange={(e) => setForm({ ...form, code: e.target.value })}
              required
            />
          </Field>
          <Field label="名称" required>
            <input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              required
            />
          </Field>
          <Field label="类型" required>
            <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })}>
              {ORG_TYPE_OPTIONS.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}（{t.value}）
                </option>
              ))}
            </select>
          </Field>
          <Field label="父节点">
            <select
              value={form.parent_id}
              onChange={(e) => setForm({ ...form, parent_id: e.target.value })}
            >
              <option value="">（根节点）</option>
              {tree.map(({ unit, depth }) => (
                <option key={unit.id} value={unit.id}>
                  {orgOptionLabel(unit, depth)}
                </option>
              ))}
            </select>
          </Field>
          <Field label="默认地点（可选，不等于☆公司）">
            <select
              value={form.default_site}
              onChange={(e) => setForm({ ...form, default_site: e.target.value })}
            >
              <option value="">（无）</option>
              {SITE_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit">创建</button>
        </form>

        <div className="admin-card">
          <h2>组织树（{orgUnits.length}）</h2>
          <ul className="admin-list admin-org-tree">
            {tree.map(({ unit, depth }) => (
              <li key={unit.id} style={{ paddingLeft: `${depth * 14}px` }}>
                <strong>{unit.name}</strong>
                <span className="muted">
                  {" "}
                  {unit.code} · {orgTypeLabel(unit.type)}
                  {unit.default_site ? ` · 默认地点 ${siteLabel(unit.default_site)}` : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

function PositionsPanel({ orgUnits, positions, onDone, onError }) {
  const [form, setForm] = useState({
    code: "",
    name: "",
    org_unit_id: "",
    domain: "",
    role_codes: ["reader"],
  });

  const toggleRole = (code) => {
    setForm((prev) => {
      const has = prev.role_codes.includes(code);
      return {
        ...prev,
        role_codes: has ? prev.role_codes.filter((c) => c !== code) : [...prev.role_codes, code],
      };
    });
  };

  const submit = async (e) => {
    e.preventDefault();
    if (!form.org_unit_id) {
      onError(new Error("请选择组织节点"));
      return;
    }
    try {
      await createPosition({
        code: form.code.trim(),
        name: form.name.trim(),
        org_unit_id: form.org_unit_id,
        domain: form.domain || null,
        role_codes: form.role_codes,
      });
      setForm({ code: "", name: "", org_unit_id: "", domain: "", role_codes: ["reader"] });
      await onDone("岗位已创建");
    } catch (err) {
      onError(err);
    }
  };

  const orgName = (id) => orgUnits.find((u) => u.id === id)?.name || id.slice(0, 8);
  const orgTree = useMemo(() => orderOrgUnitsTree(orgUnits), [orgUnits]);

  return (
    <section className="admin-grid">
      <form className="admin-card" onSubmit={submit}>
        <h2>新建岗位</h2>
        <Field label="编码" required>
          <input
            value={form.code}
            onChange={(e) => setForm({ ...form, code: e.target.value })}
            required
          />
        </Field>
        <Field label="名称" required>
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
          />
        </Field>
        <Field label="组织节点" required>
          <select
            value={form.org_unit_id}
            onChange={(e) => setForm({ ...form, org_unit_id: e.target.value })}
            required
          >
            <option value="">请选择</option>
            {orgTree.map(({ unit, depth }) => (
              <option key={unit.id} value={unit.id}>
                {orgOptionLabel(unit, depth)}
              </option>
            ))}
          </select>
        </Field>
        <Field label="专业（可空）">
          <select
            value={form.domain}
            onChange={(e) => setForm({ ...form, domain: e.target.value })}
          >
            <option value="">（无专业）</option>
            {DOMAINS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </Field>
        <fieldset className="admin-fieldset">
          <legend>角色</legend>
          {ROLE_OPTIONS.map((code) => (
            <label key={code} className="admin-check">
              <input
                type="checkbox"
                checked={form.role_codes.includes(code)}
                onChange={() => toggleRole(code)}
              />
              {code}
            </label>
          ))}
        </fieldset>
        <button type="submit">创建</button>
      </form>

      <div className="admin-card">
        <h2>岗位列表（{positions.length}）</h2>
        <ul className="admin-list">
          {positions.map((p) => (
            <li key={p.id}>
              <strong>{p.name}</strong>
              <span className="muted">
                {" "}
                {p.code} · {orgName(p.org_unit_id)}
                {p.domain ? ` · ${p.domain}` : " · 无专业"}
                {p.role_codes?.length ? ` · [${p.role_codes.join(", ")}]` : ""}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function UsersPanel({ orgUnits, positions, users, onDone, onError }) {
  const [createForm, setCreateForm] = useState({
    username: "",
    password: "",
    display_name: "",
    site: "taiyuan",
    clearance: "general",
  });
  const [bindForm, setBindForm] = useState({
    user_id: "",
    position_id: "",
    clearance: "",
  });
  const [unbindForm, setUnbindForm] = useState({
    user_id: "",
    position_id: "",
    clearance: "",
  });
  const [clearanceForm, setClearanceForm] = useState({ user_id: "", clearance: "" });
  const [estabForm, setEstabForm] = useState({ user_id: "", org_unit_id: "" });

  const selectedUnbindUser = useMemo(
    () => users.find((u) => u.id === unbindForm.user_id),
    [users, unbindForm.user_id],
  );
  const orgTree = useMemo(() => orderOrgUnitsTree(orgUnits), [orgUnits]);
  const boundPositions = useMemo(() => {
    const ids = new Set(selectedUnbindUser?.position_ids || []);
    return positions.filter((p) => ids.has(p.id));
  }, [positions, selectedUnbindUser]);

  const create = async (e) => {
    e.preventDefault();
    try {
      await createUser({
        username: createForm.username.trim(),
        password: createForm.password,
        display_name: createForm.display_name.trim(),
        site: createForm.site,
        clearance: createForm.clearance,
      });
      setCreateForm({
        username: "",
        password: "",
        display_name: "",
        site: "taiyuan",
        clearance: "general",
      });
      await onDone("用户已创建");
    } catch (err) {
      onError(err);
    }
  };

  const bind = async (e) => {
    e.preventDefault();
    if (!bindForm.clearance) {
      onError(new Error("绑岗必须选择密级"));
      return;
    }
    try {
      await bindUserPosition(bindForm.user_id, {
        positionId: bindForm.position_id,
        clearance: bindForm.clearance,
      });
      setBindForm({ user_id: "", position_id: "", clearance: "" });
      await onDone("绑岗成功");
    } catch (err) {
      onError(err);
    }
  };

  const unbind = async (e) => {
    e.preventDefault();
    if (!unbindForm.clearance) {
      onError(new Error("减岗必须选择密级"));
      return;
    }
    try {
      await unbindUserPosition(unbindForm.user_id, unbindForm.position_id, unbindForm.clearance);
      setUnbindForm({ user_id: "", position_id: "", clearance: "" });
      await onDone("减岗成功");
    } catch (err) {
      onError(err);
    }
  };

  const patchClearance = async (e) => {
    e.preventDefault();
    if (!clearanceForm.clearance) {
      onError(new Error("必须选择密级"));
      return;
    }
    try {
      await updateUserClearance(clearanceForm.user_id, clearanceForm.clearance);
      setClearanceForm({ user_id: "", clearance: "" });
      await onDone("密级已更新");
    } catch (err) {
      onError(err);
    }
  };

  const setEstab = async (e) => {
    e.preventDefault();
    try {
      await setEstablishment(estabForm.user_id, estabForm.org_unit_id);
      setEstabForm({ user_id: "", org_unit_id: "" });
      await onDone("编制已设置");
    } catch (err) {
      onError(err);
    }
  };

  const posLabel = (id) => {
    const p = positions.find((x) => x.id === id);
    return p ? `${p.code} · ${p.name}` : id.slice(0, 8);
  };

  return (
    <section className="admin-stack">
      <div className="admin-card">
        <h2>用户列表（{users.length}）</h2>
        <ul className="admin-list">
          {users.map((u) => (
            <li key={u.id}>
              <strong>{u.display_name || u.username}</strong>
              <span className="muted">
                {" "}
                @{u.username} · {siteLabel(u.site)} · 密级 {clearanceLabel(u.clearance)}
                {u.position_ids?.length
                  ? ` · 岗 ${u.position_ids.map(posLabel).join(" / ")}`
                  : " · 无岗"}
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="admin-grid">
        <form className="admin-card" onSubmit={create}>
          <h2>新建用户</h2>
          <Field label="用户名" required>
            <input
              value={createForm.username}
              onChange={(e) => setCreateForm({ ...createForm, username: e.target.value })}
              required
            />
          </Field>
          <Field label="口令" required>
            <input
              type="password"
              value={createForm.password}
              onChange={(e) => setCreateForm({ ...createForm, password: e.target.value })}
              minLength={6}
              required
            />
          </Field>
          <Field label="显示名">
            <input
              value={createForm.display_name}
              onChange={(e) => setCreateForm({ ...createForm, display_name: e.target.value })}
            />
          </Field>
          <Field label="地点（太原/朔州/苏州，非组织节点）" required>
            <select
              value={createForm.site}
              onChange={(e) => setCreateForm({ ...createForm, site: e.target.value })}
            >
              {SITE_OPTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </Field>
          <Field label="初始密级" required>
            <select
              value={createForm.clearance}
              onChange={(e) => setCreateForm({ ...createForm, clearance: e.target.value })}
              required
            >
              {CLEARANCE_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit">创建</button>
        </form>

        <form className="admin-card" onSubmit={bind}>
          <h2>绑岗 / 兼岗</h2>
          <Field label="用户" required>
            <select
              value={bindForm.user_id}
              onChange={(e) => setBindForm({ ...bindForm, user_id: e.target.value })}
              required
            >
              <option value="">请选择</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username}
                </option>
              ))}
            </select>
          </Field>
          <Field label="岗位" required>
            <select
              value={bindForm.position_id}
              onChange={(e) => setBindForm({ ...bindForm, position_id: e.target.value })}
              required
            >
              <option value="">请选择</option>
              {positions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="密级（必选）" required>
            <select
              value={bindForm.clearance}
              onChange={(e) => setBindForm({ ...bindForm, clearance: e.target.value })}
              required
            >
              <option value="">请选择密级</option>
              {CLEARANCE_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit" disabled={!bindForm.clearance}>
            绑岗
          </button>
        </form>

        <form className="admin-card" onSubmit={unbind}>
          <h2>减岗</h2>
          <Field label="用户" required>
            <select
              value={unbindForm.user_id}
              onChange={(e) =>
                setUnbindForm({ user_id: e.target.value, position_id: "", clearance: "" })
              }
              required
            >
              <option value="">请选择</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username}
                </option>
              ))}
            </select>
          </Field>
          <Field label="已绑岗位" required>
            <select
              value={unbindForm.position_id}
              onChange={(e) => setUnbindForm({ ...unbindForm, position_id: e.target.value })}
              required
            >
              <option value="">请选择</option>
              {boundPositions.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.code} · {p.name}
                </option>
              ))}
            </select>
          </Field>
          <Field label="密级（必选）" required>
            <select
              value={unbindForm.clearance}
              onChange={(e) => setUnbindForm({ ...unbindForm, clearance: e.target.value })}
              required
            >
              <option value="">请选择密级</option>
              {CLEARANCE_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit" disabled={!unbindForm.clearance}>
            减岗
          </button>
        </form>

        <form className="admin-card" onSubmit={patchClearance}>
          <h2>单独改密级</h2>
          <Field label="用户" required>
            <select
              value={clearanceForm.user_id}
              onChange={(e) => setClearanceForm({ ...clearanceForm, user_id: e.target.value })}
              required
            >
              <option value="">请选择</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username}（当前 {u.clearance}）
                </option>
              ))}
            </select>
          </Field>
          <Field label="新密级" required>
            <select
              value={clearanceForm.clearance}
              onChange={(e) => setClearanceForm({ ...clearanceForm, clearance: e.target.value })}
              required
            >
              <option value="">请选择密级</option>
              {CLEARANCE_OPTIONS.map((c) => (
                <option key={c.value} value={c.value}>
                  {c.label}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit" disabled={!clearanceForm.clearance}>
            更新密级
          </button>
        </form>

        <form className="admin-card" onSubmit={setEstab}>
          <h2>设置编制</h2>
          <Field label="用户" required>
            <select
              value={estabForm.user_id}
              onChange={(e) => setEstabForm({ ...estabForm, user_id: e.target.value })}
              required
            >
              <option value="">请选择</option>
              {users.map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username}
                </option>
              ))}
            </select>
          </Field>
          <Field label="编制组织" required>
            <select
              value={estabForm.org_unit_id}
              onChange={(e) => setEstabForm({ ...estabForm, org_unit_id: e.target.value })}
              required
            >
              <option value="">请选择</option>
              {orgTree.map(({ unit, depth }) => (
                <option key={unit.id} value={unit.id}>
                  {orgOptionLabel(unit, depth)}
                </option>
              ))}
            </select>
          </Field>
          <button type="submit">设置编制</button>
        </form>
      </div>
    </section>
  );
}

function ProjectsPanel({ users, projects, canListUsers, onDone, onError }) {
  const [createForm, setCreateForm] = useState({ code: "", name: "" });
  const [selectedProject, setSelectedProject] = useState("");
  const [members, setMembers] = useState([]);
  const [memberUserId, setMemberUserId] = useState("");

  useEffect(() => {
    if (!selectedProject) {
      setMembers([]);
      return;
    }
    listProjectMembers(selectedProject)
      .then(setMembers)
      .catch((err) => onError(err));
  }, [selectedProject, onError]);

  const create = async (e) => {
    e.preventDefault();
    try {
      await createProject({ code: createForm.code.trim(), name: createForm.name.trim() });
      setCreateForm({ code: "", name: "" });
      await onDone("项目已创建");
    } catch (err) {
      onError(err);
    }
  };

  const addMember = async (e) => {
    e.preventDefault();
    if (!selectedProject || !memberUserId) return;
    try {
      await addProjectMember(selectedProject, memberUserId);
      setMemberUserId("");
      setMembers(await listProjectMembers(selectedProject));
      await onDone("成员已加入");
    } catch (err) {
      onError(err);
    }
  };

  const removeMember = async (userId) => {
    try {
      await removeProjectMember(selectedProject, userId);
      setMembers(await listProjectMembers(selectedProject));
      await onDone("成员已移除");
    } catch (err) {
      onError(err);
    }
  };

  return (
    <section className="admin-grid">
      <form className="admin-card" onSubmit={create}>
        <h2>新建项目</h2>
        <Field label="编码" required>
          <input
            value={createForm.code}
            onChange={(e) => setCreateForm({ ...createForm, code: e.target.value })}
            required
          />
        </Field>
        <Field label="名称" required>
          <input
            value={createForm.name}
            onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
            required
          />
        </Field>
        <button type="submit">创建</button>
      </form>

      <div className="admin-card">
        <h2>项目授权</h2>
        <Field label="项目">
          <select
            value={selectedProject}
            onChange={(e) => setSelectedProject(e.target.value)}
          >
            <option value="">请选择</option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.code} · {p.name}
              </option>
            ))}
          </select>
        </Field>

        {selectedProject ? (
          <>
            <ul className="admin-list">
              {members.length === 0 ? <li className="muted">暂无成员</li> : null}
              {members.map((m) => (
                <li key={m.user_id} className="admin-list-row">
                  <span>
                    {m.display_name || m.username} <span className="muted">@{m.username}</span>
                  </span>
                  <button type="button" className="linkish" onClick={() => removeMember(m.user_id)}>
                    移除
                  </button>
                </li>
              ))}
            </ul>
            {canListUsers ? (
              <form className="admin-inline" onSubmit={addMember}>
                <select
                  value={memberUserId}
                  onChange={(e) => setMemberUserId(e.target.value)}
                  required
                >
                  <option value="">选择用户</option>
                  {users.map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username}
                    </option>
                  ))}
                </select>
                <button type="submit">加入</button>
              </form>
            ) : (
              <p className="muted">需要 users:manage 才能从用户列表选人加入</p>
            )}
          </>
        ) : null}
      </div>
    </section>
  );
}
