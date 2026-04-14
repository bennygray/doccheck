/**
 * 项目列表占位页 (C2 auth M1 交付)
 *
 * 真实的项目列表功能由 C3 project-mgmt 实现。
 * 此页承担 M1 演示"登录进入空壳系统"的作用 + 提供登出按钮。
 */
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../services/api";
import { useAuth } from "../contexts/AuthContext";

export default function ProjectsPlaceholderPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [health, setHealth] = useState<string>("checking...");

  useEffect(() => {
    api
      .health()
      .then((r) => setHealth(JSON.stringify(r)))
      .catch((e) => setHealth(`error: ${e.message}`));
  }, []);

  async function onLogout() {
    try {
      await api.logout();
    } catch {
      // 即使 API 失败也继续前端登出
    }
    logout();
    navigate("/login", { replace: true });
  }

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <h1 style={{ fontSize: 24, margin: 0 }}>围标检测系统</h1>
        <div>
          <span data-testid="welcome-user" style={{ marginRight: 12 }}>
            欢迎,{user?.username}
          </span>
          <button
            onClick={onLogout}
            data-testid="logout-btn"
            style={{ padding: "6px 12px", cursor: "pointer" }}
          >
            登出
          </button>
        </div>
      </header>

      <section style={{ marginTop: 24 }}>
        <h2 style={{ fontSize: 18 }}>项目列表</h2>
        <p style={{ color: "#666" }}>
          (项目列表、新建/编辑/删除功能将在 C3 project-mgmt 中实现)
        </p>
      </section>

      <section style={{ marginTop: 24, color: "#888", fontSize: 13 }}>
        <div>
          <strong>后端健康:</strong>
          <code data-testid="health-status" style={{ marginLeft: 8 }}>
            {health}
          </code>
        </div>
        <div style={{ marginTop: 8 }}>
          <Link to="/demo/sse">→ SSE 心跳演示 (C1 遗留)</Link>
        </div>
      </section>
    </main>
  );
}
