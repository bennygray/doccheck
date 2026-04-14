/**
 * L1: ProtectedRoute (C2)
 */
import { describe, expect, it, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProtectedRoute from "./ProtectedRoute";
import { AuthProvider, type AuthUser } from "../contexts/AuthContext";
import { clearAuthStorage, primeAuthStorage } from "../contexts/test-utils";

function App({ initialPath = "/secret" }: { initialPath?: string }) {
  return (
    <MemoryRouter initialEntries={[initialPath]}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<div>LOGIN PAGE</div>} />
          <Route
            path="/change-password"
            element={<div>CHANGE PASSWORD</div>}
          />
          <Route
            path="/secret"
            element={
              <ProtectedRoute>
                <div>SECRET CONTENT</div>
              </ProtectedRoute>
            }
          />
        </Routes>
      </AuthProvider>
    </MemoryRouter>
  );
}

const adminUser: AuthUser = {
  id: 1,
  username: "admin",
  role: "admin",
  is_active: true,
  must_change_password: false,
};

describe("ProtectedRoute", () => {
  afterEach(() => clearAuthStorage());

  it("未登录重定向到 /login", async () => {
    render(<App />);
    expect(await screen.findByText("LOGIN PAGE")).toBeInTheDocument();
    expect(screen.queryByText("SECRET CONTENT")).not.toBeInTheDocument();
  });

  it("登录后渲染 children", async () => {
    primeAuthStorage("tok", adminUser);
    render(<App />);
    expect(await screen.findByText("SECRET CONTENT")).toBeInTheDocument();
  });

  it("must_change_password=true 且不在 /change-password 时强制跳转", async () => {
    primeAuthStorage("tok", { ...adminUser, must_change_password: true });
    render(<App />);
    expect(await screen.findByText("CHANGE PASSWORD")).toBeInTheDocument();
    expect(screen.queryByText("SECRET CONTENT")).not.toBeInTheDocument();
  });

  it("must_change_password=true 在 /change-password 时不再跳", async () => {
    primeAuthStorage("tok", { ...adminUser, must_change_password: true });
    render(<App initialPath="/change-password" />);
    expect(await screen.findByText("CHANGE PASSWORD")).toBeInTheDocument();
  });
});
