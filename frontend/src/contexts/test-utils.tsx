/**
 * AuthProvider 测试 helper (C2)
 *
 * 用 renderWithAuth 包装组件,可注入预设的 token/user 状态。
 * 无需显式 mock localStorage — 会在渲染前写入,AuthProvider 的 useEffect 会读出。
 */
import { type ReactElement, type ReactNode } from "react";
import { render, type RenderResult } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider, type AuthUser } from "./AuthContext";

export interface AuthTestInit {
  token?: string | null;
  user?: AuthUser | null;
  initialEntries?: string[];
}

export function primeAuthStorage(token: string | null, user: AuthUser | null) {
  if (token) window.localStorage.setItem("auth:token", token);
  else window.localStorage.removeItem("auth:token");
  if (user) window.localStorage.setItem("auth:user", JSON.stringify(user));
  else window.localStorage.removeItem("auth:user");
}

export function renderWithAuth(
  ui: ReactElement,
  init: AuthTestInit = {},
): RenderResult {
  primeAuthStorage(init.token ?? null, init.user ?? null);
  return render(
    <MemoryRouter initialEntries={init.initialEntries ?? ["/"]}>
      <AuthProvider>{ui as ReactNode}</AuthProvider>
    </MemoryRouter>,
  );
}

export function clearAuthStorage() {
  window.localStorage.removeItem("auth:token");
  window.localStorage.removeItem("auth:user");
  window.localStorage.removeItem("auth:pendingPath");
}
