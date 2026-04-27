/**
 * 登录页 (C2 auth, US-1.1)
 *
 * 视觉:
 *  - 左栏品牌面板:品牌 mark + 标题 + 3 条功能亮点(icon + 文字)+ 版权/ICP
 *  - 左栏装饰:1px 斜线网格 10% 透明度(纯 CSS,无粒子/发光/AI 味)
 *  - 右栏白卡表单:用户名 / 密码 / 记住我 + 授权提示
 *
 * 功能契约不变:login → must_change_password 跳改密 / 否则跳 /projects
 * 新增:"记住我" checkbox → login({ remember: bool }),false 时存 sessionStorage
 *
 * 锁死不破坏的 data-testid:login-form / login-username / login-password / login-error / login-submit
 */
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Alert, Button, Checkbox, Divider, Form, Input } from "antd";
import {
  AuditOutlined,
  FileWordOutlined,
  LockOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { ApiError, api } from "../services/api";
import { authStorage, useAuth } from "../contexts/AuthContext";

const FEATURES = [
  {
    icon: <SafetyCertificateOutlined />,
    title: "多维度围标检测",
    desc: "13 维度算法 + LLM 综合研判,文本 / 报价 / 元数据 / 风格全覆盖",
  },
  {
    icon: <AuditOutlined />,
    title: "证据链自动沉淀",
    desc: "命中段落、报价匹配、元数据碰撞一键溯源,可审计可回查",
  },
  {
    icon: <FileWordOutlined />,
    title: "Word 一键导出",
    desc: "内置监管部门模板,检测完成即可生成可签发的正式报告",
  },
];

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  async function onSubmit(e: React.SyntheticEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const r = await api.login(username, password);
      login(r.access_token, r.user, { remember });
      const pending = authStorage.consumePendingPath();
      const target = r.user.must_change_password
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
    <div className="auth-shell">
      <aside className="auth-shell__brand" aria-hidden="true">
        <div className="auth-shell__brand-inner">
          <div className="auth-shell__brand-wordmark">DOCUMENTCHECK</div>
          <h1 className="auth-shell__brand-title">围标检测系统</h1>
          <p className="auth-shell__brand-subtitle">
            企业级投标文件围标串标行为检测平台
          </p>

          <ul className="auth-shell__features">
            {FEATURES.map((f) => (
              <li key={f.title}>
                <span className="auth-shell__feature-icon">{f.icon}</span>
                <div>
                  <div className="auth-shell__feature-title">{f.title}</div>
                  <div className="auth-shell__feature-desc">{f.desc}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="auth-shell__brand-footer">
          <div>© 2026 DocumentCheck · 本系统仅限授权用户使用</div>
          <div className="auth-shell__brand-footer-sub">
            v1.0 · 使用过程中如遇问题请联系管理员
          </div>
        </div>
      </aside>

      <main className="auth-shell__form">
        <div className="auth-shell__form-inner">
          <h2 className="auth-shell__form-title">欢迎登录</h2>
          <p className="auth-shell__form-subtitle">请使用管理员分配的账号登录</p>

          <Form
            layout="vertical"
            onSubmitCapture={onSubmit}
            component="form"
            data-testid="login-form"
            requiredMark={false}
            size="large"
          >
            <Form.Item label="用户名">
              <Input
                prefix={<UserOutlined style={{ color: "#8a919d" }} />}
                autoComplete="username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                placeholder="请输入用户名"
                data-testid="login-username"
                required
              />
            </Form.Item>

            <Form.Item label="密码" style={{ marginBottom: 16 }}>
              <Input.Password
                prefix={<LockOutlined style={{ color: "#8a919d" }} />}
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="请输入密码"
                data-testid="login-password"
                required
              />
            </Form.Item>

            <Form.Item style={{ marginBottom: 16 }}>
              <Checkbox
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
              >
                <span style={{ color: "#5c6370" }}>
                  记住我 <span style={{ color: "#8a919d", fontSize: 12 }}>(保持登录 24 小时)</span>
                </span>
              </Checkbox>
            </Form.Item>

            {error ? (
              <Alert
                type="error"
                message={error}
                data-testid="login-error"
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
              data-testid="login-submit"
            >
              {submitting ? "登录中..." : "登 录"}
            </Button>

            <Divider style={{ margin: "24px 0 12px", fontSize: 12 }} plain>
              <span style={{ color: "#8a919d", fontWeight: 400 }}>安全提示</span>
            </Divider>
            <p
              style={{
                fontSize: 12,
                color: "#8a919d",
                lineHeight: 1.7,
                margin: 0,
                textAlign: "center",
              }}
            >
              本系统仅限授权用户使用,所有操作均留痕审计。
              <br />
              如需账号或遇到问题,请联系系统管理员。
            </p>
          </Form>
        </div>
      </main>
    </div>
  );
}
