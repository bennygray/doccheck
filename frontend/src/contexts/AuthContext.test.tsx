/**
 * L1: AuthContext (C2)
 */
import { afterEach, describe, expect, it } from "vitest";
import { act } from "@testing-library/react";
import { renderHook } from "@testing-library/react";
import { AuthProvider, useAuth, type AuthUser } from "./AuthContext";
import { clearAuthStorage, primeAuthStorage } from "./test-utils";

const sampleUser: AuthUser = {
  id: 1,
  username: "admin",
  role: "admin",
  is_active: true,
  must_change_password: false,
};

function wrapper({ children }: { children: React.ReactNode }) {
  return <AuthProvider>{children}</AuthProvider>;
}

describe("AuthContext", () => {
  afterEach(() => {
    clearAuthStorage();
  });

  it("初始未登录", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    // hydration effect 执行后
    await act(async () => {});
    expect(result.current.hydrated).toBe(true);
    expect(result.current.token).toBeNull();
    expect(result.current.user).toBeNull();
  });

  it("login 写 state 与 localStorage", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {});
    act(() => {
      result.current.login("tok-1", sampleUser);
    });
    expect(result.current.token).toBe("tok-1");
    expect(result.current.user).toEqual(sampleUser);
    expect(window.localStorage.getItem("auth:token")).toBe("tok-1");
    expect(JSON.parse(window.localStorage.getItem("auth:user")!)).toEqual(
      sampleUser,
    );
  });

  it("logout 清 state 与 localStorage", async () => {
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {});
    act(() => result.current.login("tok-1", sampleUser));
    act(() => result.current.logout());
    expect(result.current.token).toBeNull();
    expect(result.current.user).toBeNull();
    expect(window.localStorage.getItem("auth:token")).toBeNull();
    expect(window.localStorage.getItem("auth:user")).toBeNull();
  });

  it("mount 时从 localStorage 恢复", async () => {
    primeAuthStorage("stored-tok", sampleUser);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {});
    expect(result.current.token).toBe("stored-tok");
    expect(result.current.user).toEqual(sampleUser);
  });

  it("updateUser 只改 user 不动 token", async () => {
    primeAuthStorage("stored-tok", sampleUser);
    const { result } = renderHook(() => useAuth(), { wrapper });
    await act(async () => {});
    const updated: AuthUser = { ...sampleUser, must_change_password: true };
    act(() => result.current.updateUser(updated));
    expect(result.current.user).toEqual(updated);
    expect(result.current.token).toBe("stored-tok");
  });
});
