import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { getMe, login as apiLogin, logout as apiLogout } from "./api.js";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    try {
      const me = await getMe();
      setUser(me);
      return me;
    } catch {
      setUser(null);
      return null;
    }
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  // Permissions come from DB each /me; re-fetch when tab is focused so catalog
  // sync / admin role changes show up without a full re-login.
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === "visible") {
        refresh().catch(() => {});
      }
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [refresh]);

  async function login(username, password) {
    const me = await apiLogin(username, password);
    setUser(me);
    return me;
  }

  async function logout() {
    try {
      await apiLogout();
    } finally {
      setUser(null);
    }
  }

  function hasPermission(code) {
    return Boolean(user?.permissions?.includes(code));
  }

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, hasPermission, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
