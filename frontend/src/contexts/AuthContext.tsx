/**
 * AuthContext (C2 auth)
 *
 * 职责:
 * - 持有 token / user 状态,并与 localStorage 同步(刷新页面后恢复)
 * - 提供 login / logout / updateUser 原子操作
 *
 * design.md D7 决定:只用 React Context,不引入 zustand/redux。
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface AuthUser {
  id: number;
  username: string;
  role: "admin" | "reviewer" | string;
  is_active: boolean;
  must_change_password: boolean;
}

interface AuthState {
  token: string | null;
  user: AuthUser | null;
}

interface AuthContextValue extends AuthState {
  login: (token: string, user: AuthUser) => void;
  logout: () => void;
  updateUser: (user: AuthUser) => void;
  /** 是否已从 localStorage 恢复完毕。用于初次渲染防止未登录跳转闪烁。 */
  hydrated: boolean;
}

const STORAGE_TOKEN_KEY = "auth:token";
const STORAGE_USER_KEY = "auth:user";

const AuthContext = createContext<AuthContextValue | null>(null);

function readInitial(): AuthState {
  if (typeof window === "undefined") return { token: null, user: null };
  try {
    const token = window.localStorage.getItem(STORAGE_TOKEN_KEY);
    const userRaw = window.localStorage.getItem(STORAGE_USER_KEY);
    const user = userRaw ? (JSON.parse(userRaw) as AuthUser) : null;
    if (token && user) return { token, user };
  } catch {
    // localStorage 不可用或 JSON 坏 → 重置
  }
  return { token: null, user: null };
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ token: null, user: null });
  const [hydrated, setHydrated] = useState(false);

  // 首次 mount 时从 localStorage 恢复(避免 SSR 不一致)
  useEffect(() => {
    setState(readInitial());
    setHydrated(true);
  }, []);

  const login = useCallback((token: string, user: AuthUser) => {
    setState({ token, user });
    window.localStorage.setItem(STORAGE_TOKEN_KEY, token);
    window.localStorage.setItem(STORAGE_USER_KEY, JSON.stringify(user));
  }, []);

  const logout = useCallback(() => {
    setState({ token: null, user: null });
    window.localStorage.removeItem(STORAGE_TOKEN_KEY);
    window.localStorage.removeItem(STORAGE_USER_KEY);
    // 显式登出时清 pendingPath:用户主动结束会话,无需"登录后恢复原页"
    window.localStorage.removeItem("auth:pendingPath");
  }, []);

  const updateUser = useCallback((user: AuthUser) => {
    setState((prev) => ({ ...prev, user }));
    window.localStorage.setItem(STORAGE_USER_KEY, JSON.stringify(user));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ ...state, login, logout, updateUser, hydrated }),
    [state, login, logout, updateUser, hydrated],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

/** 给 api.ts 的 interceptor 用 — 提供一个 getter,避免循环 import。 */
export const authStorage = {
  getToken(): string | null {
    try {
      return window.localStorage.getItem(STORAGE_TOKEN_KEY);
    } catch {
      return null;
    }
  },
  clear(): void {
    try {
      window.localStorage.removeItem(STORAGE_TOKEN_KEY);
      window.localStorage.removeItem(STORAGE_USER_KEY);
    } catch {
      // ignore
    }
  },
  setPendingPath(path: string): void {
    try {
      window.localStorage.setItem("auth:pendingPath", path);
    } catch {
      // ignore
    }
  },
  consumePendingPath(): string | null {
    try {
      const p = window.localStorage.getItem("auth:pendingPath");
      if (p) window.localStorage.removeItem("auth:pendingPath");
      return p;
    } catch {
      return null;
    }
  },
};
