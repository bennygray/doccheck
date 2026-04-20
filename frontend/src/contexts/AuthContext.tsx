/**
 * AuthContext (C2 auth)
 *
 * 职责:
 * - 持有 token / user 状态,并与 local/sessionStorage 同步
 * - 提供 login / logout / updateUser 原子操作
 * - 支持 "记住我":login(token, user, { remember: true })→ localStorage(跨标签持久)
 *   否则 → sessionStorage(关标签页即失效)
 *
 * 恢复顺序:localStorage 优先,其次 sessionStorage(默认行为兼容旧数据)。
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

interface AuthLoginOptions {
  /** true(默认)→ localStorage 持久;false → sessionStorage(关标签即失效) */
  remember?: boolean;
}

interface AuthContextValue extends AuthState {
  login: (token: string, user: AuthUser, opts?: AuthLoginOptions) => void;
  logout: () => void;
  updateUser: (user: AuthUser) => void;
  /** 是否已从 storage 恢复完毕。用于初次渲染防止未登录跳转闪烁。 */
  hydrated: boolean;
}

const STORAGE_TOKEN_KEY = "auth:token";
const STORAGE_USER_KEY = "auth:user";

const AuthContext = createContext<AuthContextValue | null>(null);

function safeGet(store: Storage, key: string): string | null {
  try {
    return store.getItem(key);
  } catch {
    return null;
  }
}

function safeRemoveBoth(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // ignore
  }
  try {
    window.sessionStorage.removeItem(key);
  } catch {
    // ignore
  }
}

function readInitial(): AuthState {
  if (typeof window === "undefined") return { token: null, user: null };
  // 先 local,再 session
  for (const store of [window.localStorage, window.sessionStorage]) {
    const token = safeGet(store, STORAGE_TOKEN_KEY);
    const userRaw = safeGet(store, STORAGE_USER_KEY);
    if (token && userRaw) {
      try {
        return { token, user: JSON.parse(userRaw) as AuthUser };
      } catch {
        // JSON 坏 → 继续试 session
      }
    }
  }
  return { token: null, user: null };
}

function pickStore(remember: boolean): Storage {
  return remember ? window.localStorage : window.sessionStorage;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ token: null, user: null });
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setState(readInitial());
    setHydrated(true);
  }, []);

  const login = useCallback(
    (token: string, user: AuthUser, opts?: AuthLoginOptions) => {
      const remember = opts?.remember ?? true;
      setState({ token, user });
      // 先把另一处清掉,避免残留
      safeRemoveBoth(STORAGE_TOKEN_KEY);
      safeRemoveBoth(STORAGE_USER_KEY);
      const store = pickStore(remember);
      try {
        store.setItem(STORAGE_TOKEN_KEY, token);
        store.setItem(STORAGE_USER_KEY, JSON.stringify(user));
      } catch {
        // storage 满 / 禁用 → 静默
      }
    },
    [],
  );

  const logout = useCallback(() => {
    setState({ token: null, user: null });
    safeRemoveBoth(STORAGE_TOKEN_KEY);
    safeRemoveBoth(STORAGE_USER_KEY);
    safeRemoveBoth("auth:pendingPath");
  }, []);

  const updateUser = useCallback((user: AuthUser) => {
    setState((prev) => ({ ...prev, user }));
    // 写回当前用户所在的那个 store(二选一)
    const userRaw = JSON.stringify(user);
    if (safeGet(window.localStorage, STORAGE_TOKEN_KEY)) {
      try {
        window.localStorage.setItem(STORAGE_USER_KEY, userRaw);
      } catch {
        // ignore
      }
    } else if (safeGet(window.sessionStorage, STORAGE_TOKEN_KEY)) {
      try {
        window.sessionStorage.setItem(STORAGE_USER_KEY, userRaw);
      } catch {
        // ignore
      }
    }
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

/** 给 api.ts 的 interceptor 用 — 避免循环 import;local 优先 session 兜底。 */
export const authStorage = {
  getToken(): string | null {
    return (
      safeGet(window.localStorage, STORAGE_TOKEN_KEY) ??
      safeGet(window.sessionStorage, STORAGE_TOKEN_KEY)
    );
  },
  clear(): void {
    safeRemoveBoth(STORAGE_TOKEN_KEY);
    safeRemoveBoth(STORAGE_USER_KEY);
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
