/**
 * 登录页 (C2 auth, US-1.1)
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../services/api";
import { authStorage, useAuth } from "../contexts/AuthContext";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const r = await api.login(username, password);
      login(r.access_token, r.user);
      const pending = authStorage.consumePendingPath();
      const target =
        r.user.must_change_password
          ? "/change-password"
          : pending && pending !== "/login"
            ? pending
            : "/projects";
      navigate(target, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        const d = err.detail as { retry_after_seconds?: number } | undefined;
        const secs = d?.retry_after_seconds ?? 0;
        setError(`账户已锁定,请 ${Math.ceil(secs / 60)} 分钟后再试`);
      } else if (err instanceof ApiError && err.status === 403) {
        setError("账户已被禁用,请联系管理员");
      } else {
        setError("用户名或密码错误");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main
      style={{
        padding: 32,
        fontFamily: "system-ui, sans-serif",
        maxWidth: 360,
        margin: "80px auto",
      }}
    >
      <h1 style={{ fontSize: 24 }}>围标检测系统</h1>
      <p style={{ color: "#666" }}>请登录</p>
      <form onSubmit={onSubmit} data-testid="login-form">
        <label style={{ display: "block", marginTop: 16 }}>
          <span>用户名</span>
          <input
            type="text"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            data-testid="login-username"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>
        <label style={{ display: "block", marginTop: 12 }}>
          <span>密码</span>
          <input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            data-testid="login-password"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>
        {error ? (
          <p
            data-testid="login-error"
            style={{ color: "#c00", marginTop: 12 }}
            role="alert"
          >
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          data-testid="login-submit"
          style={{
            marginTop: 16,
            padding: "8px 16px",
            width: "100%",
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? "登录中..." : "登录"}
        </button>
      </form>
    </main>
  );
}
