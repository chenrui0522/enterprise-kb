import { NavLink, Navigate, Outlet } from "react-router-dom";
import { useAuth } from "./auth.jsx";

function ChatNavIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M21 11.5a8.38 8.38 0 01-.9 3.8 8.5 8.5 0 01-7.6 4.7 8.38 8.38 0 01-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 01-.9-3.8 8.5 8.5 0 014.7-7.6 8.38 8.38 0 013.8-.9h.5a8.48 8.48 0 018 8v.5z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DocsNavIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8l-6-6z"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d="M14 2v6h6M16 13H8M16 17H8M10 9H8" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function AdminNavIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="2" />
      <path
        d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
      />
    </svg>
  );
}

function LogoutNavIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path
        d="M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function App() {
  const { user, loading, logout, hasPermission } = useAuth();

  if (loading) {
    return <main className="login-page">加载中…</main>;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const canManage =
    hasPermission("orgs:manage") ||
    hasPermission("users:manage") ||
    hasPermission("projects:manage");
  const canAudit = hasPermission("audit:read");
  const canDocs = hasPermission("documents:write") || hasPermission("documents:read");

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header-user">
          <strong>{user.display_name || user.username}</strong>
          <span className="muted">
            {" "}
            · {user.site} · 密级 {user.clearance}
          </span>
        </div>
        <nav className="app-nav">
          <NavLink to="/" end className={({ isActive }) => `app-nav-item${isActive ? " active" : ""}`}>
            <ChatNavIcon />
            问答
          </NavLink>
          {canDocs ? (
            <NavLink
              to="/documents"
              className={({ isActive }) => `app-nav-item${isActive ? " active" : ""}`}
            >
              <DocsNavIcon />
              文档
            </NavLink>
          ) : null}
          {canManage ? (
            <NavLink to="/admin" className={({ isActive }) => `app-nav-item${isActive ? " active" : ""}`}>
              <AdminNavIcon />
              管理
            </NavLink>
          ) : null}
          {canAudit ? (
            <NavLink
              to="/admin?tab=audit"
              className={({ isActive }) => `app-nav-item${isActive ? " active" : ""}`}
            >
              <AdminNavIcon />
              审计
            </NavLink>
          ) : null}
          <button type="button" className="app-nav-item app-nav-logout" onClick={() => logout()}>
            <LogoutNavIcon />
            退出
          </button>
        </nav>
      </header>
      <Outlet />
    </div>
  );
}
