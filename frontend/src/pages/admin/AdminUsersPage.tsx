/**
 * 用户管理页 (C17 admin-users, US-8.1~8.3)
 *
 * - 用户列表 antd Table(列:用户名 / 角色 / 状态 / 创建时间 / 操作)
 * - 创建用户 → Modal 表单(原"按钮切表单"改成弹窗,更 B2B)
 * - 启用/禁用开关
 * - 仅 admin 可访问(RoleGuard 在路由层守护)
 *
 * 契约不变 data-testid:
 *   - create-user-btn / create-user-form / input-username / input-password / input-role
 *   - form-error / users-table / user-row-<id> / toggle-active-<id> / error-msg
 * 壳由 AppLayout 提供
 */
import { useCallback, useEffect, useState } from "react";
import {
  Alert,
  App,
  Breadcrumb,
  Button,
  Card,
  Form,
  Input,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { TableProps } from "antd";
import { PlusOutlined, UserOutlined } from "@ant-design/icons";
import { Link } from "react-router-dom";
import { ApiError, api } from "../../services/api";
import type { AdminUser } from "../../types";

export default function AdminUsersPage() {
  const { message } = App.useApp();
  const [users, setUsers] = useState<AdminUser[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

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

  function resetForm() {
    setFormUsername("");
    setFormPassword("");
    setFormRole("reviewer");
    setFormError("");
  }

  async function handleCreate(e: React.SyntheticEvent) {
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
      resetForm();
      await loadUsers();
      void message.success("用户创建成功");
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "创建失败");
    } finally {
      setFormLoading(false);
    }
  }

  async function handleToggleActive(u: AdminUser) {
    try {
      await api.updateUser(u.id, { is_active: !u.is_active });
      await loadUsers();
      void message.success(u.is_active ? "已禁用" : "已启用");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "操作失败");
    }
  }

  const columns: TableProps<AdminUser>["columns"] = [
    {
      title: "用户名",
      dataIndex: "username",
      key: "username",
      render: (name: string) => (
        <Space size={6}>
          <UserOutlined style={{ color: "#8a919d" }} />
          <Typography.Text strong>{name}</Typography.Text>
        </Space>
      ),
    },
    {
      title: "角色",
      dataIndex: "role",
      key: "role",
      width: 120,
      render: (role: string) =>
        role === "admin" ? (
          <Tag color="blue" style={{ margin: 0 }}>管理员</Tag>
        ) : (
          <Tag style={{ margin: 0 }}>审查员</Tag>
        ),
    },
    {
      title: "状态",
      dataIndex: "is_active",
      key: "is_active",
      width: 100,
      render: (active: boolean) =>
        active ? (
          <Tag color="success" style={{ margin: 0 }}>启用</Tag>
        ) : (
          <Tag color="error" style={{ margin: 0 }}>禁用</Tag>
        ),
    },
    {
      title: "创建时间",
      dataIndex: "created_at",
      key: "created_at",
      width: 180,
      render: (iso: string) => (
        <span style={{ color: "#5c6370", fontSize: 13 }}>
          {new Date(iso).toLocaleString("zh-CN")}
        </span>
      ),
    },
    {
      title: "操作",
      key: "actions",
      width: 100,
      render: (_: unknown, u) => (
        <Button
          size="small"
          type={u.is_active ? "default" : "primary"}
          danger={u.is_active}
          onClick={() => handleToggleActive(u)}
          data-testid={`toggle-active-${u.id}`}
        >
          {u.is_active ? "禁用" : "启用"}
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">首页</Link> },
          { title: "管理" },
          { title: "用户管理" },
        ]}
        style={{ marginBottom: 12 }}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          marginBottom: 20,
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <div>
          <Typography.Title level={3} style={{ margin: 0, fontWeight: 600 }}>
            用户管理
          </Typography.Title>
          <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
            管理系统内的所有账号,支持启用 / 禁用和创建新用户
          </Typography.Paragraph>
        </div>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          data-testid="create-user-btn"
          onClick={() => {
            resetForm();
            setShowForm(true);
          }}
        >
          创建用户
        </Button>
      </div>

      {error && (
        <Alert
          type="error"
          message={error}
          data-testid="error-msg"
          showIcon
          closable
          onClose={() => setError("")}
          style={{ marginBottom: 16 }}
        />
      )}

      <Card variant="outlined" styles={{ body: { padding: 0 } }}>
        <Table<AdminUser>
          rowKey="id"
          columns={columns}
          dataSource={users}
          loading={loading}
          data-testid="users-table"
          onRow={(record) =>
            ({
              "data-testid": `user-row-${record.id}`,
            }) as React.HTMLAttributes<HTMLElement>
          }
          pagination={users.length > 20 ? { pageSize: 20 } : false}
          locale={{
            emptyText: (
              <div style={{ padding: 32, color: "#8a919d" }}>暂无用户</div>
            ),
          }}
        />
      </Card>

      <Modal
        open={showForm}
        title="创建用户"
        onCancel={() => {
          setShowForm(false);
          resetForm();
        }}
        footer={null}
        destroyOnHidden
        width={480}
      >
        <Form
          layout="vertical"
          component="form"
          onSubmitCapture={handleCreate}
          data-testid="create-user-form"
          requiredMark={false}
          style={{ marginTop: 8 }}
        >
          <Form.Item label="用户名" required>
            <Input
              value={formUsername}
              onChange={(e) => setFormUsername(e.target.value)}
              required
              placeholder="请输入用户名"
              data-testid="input-username"
              autoComplete="off"
            />
          </Form.Item>

          <Form.Item label="密码" required extra="至少 8 位">
            <Input.Password
              value={formPassword}
              onChange={(e) => setFormPassword(e.target.value)}
              required
              minLength={8}
              placeholder="请输入密码"
              data-testid="input-password"
              autoComplete="new-password"
            />
          </Form.Item>

          <Form.Item label="角色">
            <Select
              value={formRole}
              onChange={setFormRole}
              data-testid="input-role"
              options={[
                { value: "reviewer", label: "审查员" },
                { value: "admin", label: "管理员" },
              ]}
            />
          </Form.Item>

          {formError && (
            <Alert
              type="error"
              message={formError}
              data-testid="form-error"
              showIcon
              style={{ marginBottom: 12 }}
            />
          )}

          <Space style={{ width: "100%", justifyContent: "flex-end" }}>
            <Button
              onClick={() => {
                setShowForm(false);
                resetForm();
              }}
            >
              取消
            </Button>
            <Button type="primary" htmlType="submit" loading={formLoading}>
              {formLoading ? "创建中..." : "确认创建"}
            </Button>
          </Space>
        </Form>
      </Modal>
    </div>
  );
}
