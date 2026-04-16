/**
 * 用户管理页 (C17 admin-users, US-8.1~8.3)
 *
 * - 用户列表（username / role / status / created_at）
 * - 创建用户表单
 * - 启用/禁用开关
 * - 仅 admin 可访问（RoleGuard 在路由层守护）
 */
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../services/api";
import type { AdminUser } from "../../types";

export default function AdminUsersPage() {
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  // 创建用户表单
  const [showForm, setShowForm] = useState(false);
  const [formUsername, setFormUsername] = useState("");
  const [formPassword, setFormPassword] = useState("");
  const [formRole, setFormRole] = useState("reviewer");
  const [formError, setFormError] = useState("");
  const [formLoading, setFormLoading] = useState(false);

  const loadUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await api.getUsers();
      setUsers(data);
      setError("");
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "加载用户列表失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadUsers();
  }, [loadUsers]);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setFormLoading(true);
    setFormError("");
    try {
      await api.createUser({
        username: formUsername,
        password: formPassword,
        role: formRole,
      });
      setShowForm(false);
      setFormUsername("");
      setFormPassword("");
      setFormRole("reviewer");
      await loadUsers();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "创建失败");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleToggleActive(user: AdminUser) {
    try {
      await api.updateUser(user.id, { is_active: !user.is_active });
      await loadUsers();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败");
    }
  }

  return (
    <main style={{ padding: 32, fontFamily: "system-ui, sans-serif" }}>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 24,
        }}
      >
        <h1 style={{ fontSize: 24, margin: 0 }}>用户管理</h1>
        <nav style={{ display: "flex", gap: 12 }}>
          <Link to="/admin/rules">规则配置</Link>
          <Link to="/projects">返回项目</Link>
        </nav>
      </header>

      {error && (
        <div
          data-testid="error-msg"
          style={{ color: "red", marginBottom: 16 }}
        >
          {error}
        </div>
      )}

      <button
        data-testid="create-user-btn"
        onClick={() => setShowForm(!showForm)}
        style={{ marginBottom: 16, padding: "8px 16px", cursor: "pointer" }}
      >
        {showForm ? "取消" : "创建用户"}
      </button>

      {showForm && (
        <form
          onSubmit={handleCreate}
          data-testid="create-user-form"
          style={{
            marginBottom: 24,
            padding: 16,
            border: "1px solid #ccc",
            borderRadius: 4,
          }}
        >
          <div style={{ marginBottom: 8 }}>
            <label>
              用户名：
              <input
                data-testid="input-username"
                value={formUsername}
                onChange={(e) => setFormUsername(e.target.value)}
                required
                style={{ marginLeft: 8 }}
              />
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label>
              密码：
              <input
                data-testid="input-password"
                type="password"
                value={formPassword}
                onChange={(e) => setFormPassword(e.target.value)}
                required
                minLength={8}
                style={{ marginLeft: 8 }}
              />
            </label>
          </div>
          <div style={{ marginBottom: 8 }}>
            <label>
              角色：
              <select
                data-testid="input-role"
                value={formRole}
                onChange={(e) => setFormRole(e.target.value)}
                style={{ marginLeft: 8 }}
              >
                <option value="reviewer">审查员</option>
                <option value="admin">管理员</option>
              </select>
            </label>
          </div>
          {formError && (
            <div data-testid="form-error" style={{ color: "red", marginBottom: 8 }}>
              {formError}
            </div>
          )}
          <button
            type="submit"
            disabled={formLoading}
            style={{ padding: "6px 16px", cursor: "pointer" }}
          >
            {formLoading ? "创建中..." : "确认创建"}
          </button>
        </form>
      )}

      {loading ? (
        <p>加载中...</p>
      ) : (
        <table
          data-testid="users-table"
          style={{ width: "100%", borderCollapse: "collapse" }}
        >
          <thead>
            <tr style={{ borderBottom: "2px solid #333", textAlign: "left" }}>
              <th style={{ padding: 8 }}>用户名</th>
              <th style={{ padding: 8 }}>角色</th>
              <th style={{ padding: 8 }}>状态</th>
              <th style={{ padding: 8 }}>创建时间</th>
              <th style={{ padding: 8 }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr
                key={u.id}
                data-testid={`user-row-${u.id}`}
                style={{ borderBottom: "1px solid #eee" }}
              >
                <td style={{ padding: 8 }}>{u.username}</td>
                <td style={{ padding: 8 }}>
                  {u.role === "admin" ? "管理员" : "审查员"}
                </td>
                <td style={{ padding: 8 }}>
                  <span
                    style={{
                      color: u.is_active ? "#2ecc71" : "#c00",
                      fontWeight: 600,
                    }}
                  >
                    {u.is_active ? "启用" : "禁用"}
                  </span>
                </td>
                <td style={{ padding: 8 }}>
                  {new Date(u.created_at).toLocaleString("zh-CN")}
                </td>
                <td style={{ padding: 8 }}>
                  <button
                    data-testid={`toggle-active-${u.id}`}
                    onClick={() => handleToggleActive(u)}
                    style={{
                      padding: "4px 12px",
                      cursor: "pointer",
                      color: u.is_active ? "#c00" : "#2ecc71",
                    }}
                  >
                    {u.is_active ? "禁用" : "启用"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </main>
  );
}
