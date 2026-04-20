/**
 * 修改密码页 (C2 auth, US-1.4)
 *
 * 视觉:沿用 LoginPage 双栏商务布局,保持登录流一体感
 * 功能契约不变:改密成功 → logout → 跳 /login + notice
 * 锁死不破坏的 data-testid:change-password-form / old-password / new-password
 *   / confirm-password / change-password-error / change-password-submit / force-notice
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Form, Input } from "antd";
import { LockOutlined } from "@ant-design/icons";
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

  async function onSubmit(e: React.SyntheticEvent) {
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
    <div className="auth-shell">
      <aside className="auth-shell__brand" aria-hidden="true">
        <div className="auth-shell__brand-inner">
          <div className="auth-shell__brand-wordmark">DOCUMENTCHECK</div>
          <h1 className="auth-shell__brand-title">围标检测系统</h1>
          <p className="auth-shell__brand-subtitle">
            企业级投标文件围标串标行为检测平台
          </p>
        </div>
        <div className="auth-shell__brand-footer">
          DocumentCheck · 本系统仅限授权用户使用
        </div>
      </aside>

      <main className="auth-shell__form">
        <div className="auth-shell__form-inner">
          <h2 className="auth-shell__form-title">修改密码</h2>
          <p className="auth-shell__form-subtitle">
            {user?.username ? `当前账号:${user.username}` : "为了账户安全,请设置新密码"}
          </p>

          {user?.must_change_password ? (
            <Alert
              type="warning"
              showIcon
              message="首次登录需修改默认密码后方可继续使用"
              data-testid="force-notice"
              style={{ marginBottom: 20 }}
            />
          ) : null}

          <Form
            layout="vertical"
            onSubmitCapture={onSubmit}
            component="form"
            data-testid="change-password-form"
            requiredMark={false}
            size="large"
          >
            <Form.Item label="原密码">
              <Input.Password
                prefix={<LockOutlined style={{ color: "#8a919d" }} />}
                value={oldPwd}
                onChange={(e) => setOldPwd(e.target.value)}
                placeholder="请输入原密码"
                data-testid="old-password"
                required
              />
            </Form.Item>

            <Form.Item
              label="新密码"
              extra={<span style={{ fontSize: 12 }}>至少 8 位,同时包含字母和数字</span>}
            >
              <Input.Password
                prefix={<LockOutlined style={{ color: "#8a919d" }} />}
                value={newPwd}
                onChange={(e) => setNewPwd(e.target.value)}
                placeholder="请输入新密码"
                data-testid="new-password"
                required
              />
            </Form.Item>

            <Form.Item label="确认新密码">
              <Input.Password
                prefix={<LockOutlined style={{ color: "#8a919d" }} />}
                value={confirmPwd}
                onChange={(e) => setConfirmPwd(e.target.value)}
                placeholder="请再次输入新密码"
                data-testid="confirm-password"
                required
              />
            </Form.Item>

            {error ? (
              <Alert
                type="error"
                message={error}
                data-testid="change-password-error"
                role="alert"
                showIcon
                style={{ marginBottom: 16 }}
              />
            ) : null}

            <Button
              type="primary"
              htmlType="submit"
              block
              loading={submitting}
              data-testid="change-password-submit"
            >
              {submitting ? "提交中..." : "确认修改"}
            </Button>
          </Form>
        </div>
      </main>
    </div>
  );
}
