import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, getToken, setToken, clearToken } from "../api/client";

type AuthUser = { id: number; username: string } | null;

type AuthContextValue = {
  token: string | null;
  user: AuthUser;
  loading: boolean;
  login: (newToken: string) => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setTokenState] = useState<string | null>(getToken);
  const [user, setUser] = useState<AuthUser>(null);
  const [loading, setLoading] = useState(true);

  const loadUser = useCallback(async () => {
    const t = getToken();
    if (!t) {
      setUser(null);
      setTokenState(null);
      setLoading(false);
      return;
    }
    try {
      const me = await api.auth.me(t);
      setUser({ id: me.id, username: me.username });
      setTokenState(t);
    } catch {
      clearToken();
      setTokenState(null);
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUser();
  }, [loadUser]);

  const login = useCallback((newToken: string) => {
    setToken(newToken);
    setTokenState(newToken);
    setLoading(true);
    void loadUser();
  }, [loadUser]);

  const logout = useCallback(() => {
    clearToken();
    setTokenState(null);
    setUser(null);
  }, []);

  useEffect(() => {
    const onUnauthorized = () => {
      logout();
      setLoading(false);
    };
    window.addEventListener("wifiaudit:unauthorized", onUnauthorized);
    return () => window.removeEventListener("wifiaudit:unauthorized", onUnauthorized);
  }, [logout]);

  const value = useMemo<AuthContextValue>(
    () => ({ token, user, loading, login, logout, refreshUser: loadUser }),
    [token, user, loading, login, logout, loadUser]
  );

  return createElement(AuthContext.Provider, { value }, children);
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) {
    throw new Error("useAuth must be used inside AuthProvider");
  }
  return ctx;
}
