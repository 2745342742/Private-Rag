import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { apiFetch, ApiError, getStoredToken, setStoredToken } from "./api";
import { AUTH_USER_KEY } from "./config";

export type AuthUser = {
  id: string;
  username: string;
  display_name?: string | null;
  created_at?: string | null;
};

type AuthContextValue = {
  user: AuthUser | null;
  token: string | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  register: (
    username: string,
    password: string,
    displayName?: string,
  ) => Promise<void>;
  logout: () => void;
  refreshMe: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function readCachedUser(): AuthUser | null {
  try {
    const raw = localStorage.getItem(AUTH_USER_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

function cacheUser(user: AuthUser | null): void {
  try {
    if (user) localStorage.setItem(AUTH_USER_KEY, JSON.stringify(user));
    else localStorage.removeItem(AUTH_USER_KEY);
  } catch {
    /* ignore */
  }
}

type TokenResponse = {
  access_token: string;
  user: AuthUser;
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [token, setToken] = useState<string | null>(() => getStoredToken());
  const [user, setUser] = useState<AuthUser | null>(() => readCachedUser());
  const [loading, setLoading] = useState(Boolean(getStoredToken()));

  const applySession = useCallback((accessToken: string, nextUser: AuthUser) => {
    setStoredToken(accessToken);
    cacheUser(nextUser);
    setToken(accessToken);
    setUser(nextUser);
  }, []);

  const clearSession = useCallback(() => {
    setStoredToken(null);
    cacheUser(null);
    setToken(null);
    setUser(null);
  }, []);

  const refreshMe = useCallback(async () => {
    const t = getStoredToken();
    if (!t) {
      clearSession();
      setLoading(false);
      return;
    }
    try {
      const data = await apiFetch<{ user: AuthUser }>("/auth/me");
      applySession(t, data.user);
    } catch (err) {
      if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
        clearSession();
      }
    } finally {
      setLoading(false);
    }
  }, [applySession, clearSession]);

  useEffect(() => {
    void refreshMe();
  }, [refreshMe]);

  const login = useCallback(
    async (username: string, password: string) => {
      const data = await apiFetch<TokenResponse>("/auth/login", {
        method: "POST",
        auth: false,
        body: { username, password },
      });
      applySession(data.access_token, data.user);
    },
    [applySession],
  );

  const register = useCallback(
    async (username: string, password: string, displayName?: string) => {
      const data = await apiFetch<TokenResponse>("/auth/register", {
        method: "POST",
        auth: false,
        body: {
          username,
          password,
          display_name: displayName || null,
        },
      });
      applySession(data.access_token, data.user);
    },
    [applySession],
  );

  const logout = useCallback(() => {
    clearSession();
  }, [clearSession]);

  const value = useMemo(
    () => ({ user, token, loading, login, register, logout, refreshMe }),
    [user, token, loading, login, register, logout, refreshMe],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth 必须在 AuthProvider 内使用");
  return ctx;
}
