import { useState } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import BrandLogo, { BRAND_PRODUCT_NAME } from "../BrandLogo.jsx";
import { useAuth } from "../auth.jsx";

export default function LoginPage() {
  const { user, login, loading } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  if (!loading && user) {
    return <Navigate to="/" replace />;
  }

  async function onSubmit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await login(username.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err.message || "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <div className="login-brand">
          <BrandLogo size={56} />
          <div>
            <h1>{BRAND_PRODUCT_NAME}</h1>
            <p className="login-brand-en">AUTOLINE LOGISTICS TECHNOLOGY</p>
          </div>
        </div>
        <p>请使用工号账号登录</p>
        <label>
          用户名
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required />
        </label>
        <label>
          密码
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
            required
          />
        </label>
        {error ? <p className="login-error">{error}</p> : null}
        <button type="submit" disabled={busy}>
          {busy ? "登录中…" : "登录"}
        </button>
      </form>
    </main>
  );
}
