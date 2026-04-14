/**
 * 修改密码页 (C2 auth, US-1.4)
 *
 * 改密成功后:清 token(旧 token 已在后端失效)→ 跳 /login 提示用新密码登录
 */
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { ApiError, api } from "../services/api";
import { useAuth } from "../contexts/AuthContext";

function validate(pwd: string): string | null {
  if (pwd.length < 8) return "密码长度至少 8 位";
  if (!/[A-Za-z]/.test(pwd)) return "密码必须包含至少一个字母";
  if (!/\d/.test(pwd)) return "密码必须包含至少一个数字";
  return null;
}

export default function ChangePasswordPage() {
  const [oldPwd, setOldPwd] = useState("");
  const [newPwd, setNewPwd] = useState("");
  const [confirmPwd, setConfirmPwd] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { logout, user } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (newPwd !== confirmPwd) {
      setError("两次输入的新密码不一致");
      return;
    }
    const problem = validate(newPwd);
    if (problem) {
      setError(problem);
      return;
    }

    setSubmitting(true);
    try {
      await api.changePassword(oldPwd, newPwd);
      // 改密后旧 token 立即失效 → 前端清 token,提示重新登录
      logout();
      navigate("/login", {
        replace: true,
        state: { notice: "密码已修改,请使用新密码登录" },
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) {
        setError("原密码错误");
      } else if (err instanceof ApiError && err.status === 422) {
        setError("新密码不符合规则(至少 8 位,含字母和数字)");
      } else {
        setError("修改失败,请稍后重试");
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
        maxWidth: 420,
        margin: "60px auto",
      }}
    >
      <h1 style={{ fontSize: 22 }}>修改密码</h1>
      {user?.must_change_password ? (
        <p style={{ color: "#a60" }} data-testid="force-notice">
          首次登录需修改默认密码后方可继续使用
        </p>
      ) : null}
      <form onSubmit={onSubmit} data-testid="change-password-form">
        <label style={{ display: "block", marginTop: 12 }}>
          <span>原密码</span>
          <input
            type="password"
            value={oldPwd}
            onChange={(e) => setOldPwd(e.target.value)}
            required
            data-testid="old-password"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>
        <label style={{ display: "block", marginTop: 12 }}>
          <span>新密码(≥8 位,含字母和数字)</span>
          <input
            type="password"
            value={newPwd}
            onChange={(e) => setNewPwd(e.target.value)}
            required
            data-testid="new-password"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>
        <label style={{ display: "block", marginTop: 12 }}>
          <span>确认新密码</span>
          <input
            type="password"
            value={confirmPwd}
            onChange={(e) => setConfirmPwd(e.target.value)}
            required
            data-testid="confirm-password"
            style={{ display: "block", width: "100%", padding: 8, marginTop: 4 }}
          />
        </label>
        {error ? (
          <p
            data-testid="change-password-error"
            style={{ color: "#c00", marginTop: 12 }}
            role="alert"
          >
            {error}
          </p>
        ) : null}
        <button
          type="submit"
          disabled={submitting}
          data-testid="change-password-submit"
          style={{
            marginTop: 16,
            padding: "8px 16px",
            width: "100%",
            cursor: submitting ? "not-allowed" : "pointer",
          }}
        >
          {submitting ? "提交中..." : "确认修改"}
        </button>
      </form>
    </main>
  );
}
