/**
 * 应用主骨架 —— 左侧导航 + 顶栏 + 内容区
 *
 * 设计参照:Jira / Linear / Notion 等 B2B 工具的左栏布局(避免政府门户 / AI 看板风)
 * 商务大气:220px 左栏 + 顶栏 52px + 克制灰底;主色只出现在"当前选中"那一条
 *
 * 锁死 testid(从旧 ProjectListPage header 搬来,L3 测试已依赖):
 *   - welcome-user  / logout-btn / admin-link
 */
import { useMemo } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router-dom";
import { Avatar, Dropdown, Layout, Menu, Space, Typography } from "antd";
import {
  AppstoreOutlined,
  AuditOutlined,
  FileSearchOutlined,
  LogoutOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { api } from "../../services/api";
import { useAuth } from "../../contexts/AuthContext";

const { Header, Sider, Content } = Layout;

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  async function onLogout() {
    try {
      await api.logout();
    } catch {
      // 前端登出优先
    }
    logout();
    navigate("/login", { replace: true });
  }

  const menuItems = useMemo(() => {
    const items: Array<{
      key: string;
      icon: React.ReactNode;
      label: React.ReactNode;
      children?: Array<{ key: string; label: React.ReactNode }>;
    }> = [
      {
        key: "/projects",
        icon: <AppstoreOutlined />,
        label: <Link to="/projects">项目</Link>,
      },
    ];
    if (user?.role === "admin") {
      items.push({
        key: "admin",
        icon: <SettingOutlined />,
        label: "管理",
        children: [
          {
            key: "/admin/users",
            label: (
              <Link to="/admin/users" data-testid="admin-link">
                用户管理
              </Link>
            ),
          },
          {
            key: "/admin/rules",
            label: <Link to="/admin/rules">规则配置</Link>,
          },
          {
            key: "/admin/llm",
            label: <Link to="/admin/llm">LLM 配置</Link>,
          },
        ],
      });
    }
    return items;
  }, [user?.role]);

  // 当前路由高亮:精确匹配二级子项,或匹配一级前缀
  const selectedKey = useMemo(() => {
    const p = location.pathname;
    if (p.startsWith("/admin/users")) return "/admin/users";
    if (p.startsWith("/admin/rules")) return "/admin/rules";
    if (p.startsWith("/admin/llm")) return "/admin/llm";
    if (p.startsWith("/reports")) return "/projects"; // 报告属于项目范畴
    if (p.startsWith("/projects")) return "/projects";
    return p;
  }, [location.pathname]);

  const openKeys = useMemo(() => {
    if (location.pathname.startsWith("/admin")) return ["admin"];
    return [];
  }, [location.pathname]);

  const userMenuItems = [
    {
      key: "change-password",
      icon: <SafetyCertificateOutlined />,
      label: <Link to="/change-password">修改密码</Link>,
    },
    {
      key: "logout",
      icon: <LogoutOutlined />,
      danger: true,
      label: (
        <span data-testid="logout-btn" onClick={onLogout}>
          登出
        </span>
      ),
    },
  ];

  return (
    <Layout style={{ minHeight: "100vh" }}>
      <Sider
        width={220}
        style={{
          background: "#ffffff",
          borderRight: "1px solid #e4e7ed",
          boxShadow: "none",
          position: "sticky",
          top: 0,
          height: "100vh",
          overflow: "auto",
        }}
      >
        <div
          style={{
            height: 56,
            padding: "0 20px",
            display: "flex",
            flexDirection: "column",
            justifyContent: "center",
            borderBottom: "1px solid #e4e7ed",
            gap: 2,
          }}
        >
          <div
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: "#1d4584",
              letterSpacing: 1,
              lineHeight: 1.1,
            }}
          >
            围标检测
          </div>
          <div
            style={{
              fontSize: 10,
              color: "#8a919d",
              letterSpacing: 2.2,
              fontWeight: 500,
              lineHeight: 1,
            }}
          >
            DOCUMENTCHECK
          </div>
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          defaultOpenKeys={openKeys}
          items={menuItems}
          style={{ border: "none", padding: "12px 8px" }}
        />
        <SidebarFooter />
      </Sider>

      <Layout>
        <Header
          style={{
            height: 52,
            padding: "0 24px",
            background: "#ffffff",
            borderBottom: "1px solid #e4e7ed",
            display: "flex",
            alignItems: "center",
            justifyContent: "flex-end",
            lineHeight: "52px",
          }}
        >
          <Dropdown
            menu={{ items: userMenuItems }}
            placement="bottomRight"
            trigger={["click"]}
          >
            <Space
              style={{ cursor: "pointer", color: "#1f2328", padding: "0 8px" }}
              data-testid="welcome-user"
            >
              <Avatar
                size={28}
                icon={<UserOutlined />}
                style={{ background: "#1d4584", verticalAlign: "middle" }}
              />
              <Typography.Text
                style={{ fontSize: 13, color: "#1f2328" }}
                title={user?.username}
              >
                {user?.username ?? "用户"}
              </Typography.Text>
              {user?.role === "admin" ? (
                <Typography.Text
                  style={{
                    fontSize: 11,
                    color: "#5c6370",
                    background: "#eef3fb",
                    padding: "2px 6px",
                    borderRadius: 4,
                    marginLeft: 4,
                  }}
                >
                  管理员
                </Typography.Text>
              ) : null}
            </Space>
          </Dropdown>
        </Header>
        <Content
          style={{
            background: "#f5f7fa",
            padding: 24,
            minHeight: "calc(100vh - 52px)",
          }}
        >
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  );
}

function SidebarFooter() {
  return (
    <div
      style={{
        position: "absolute",
        bottom: 16,
        left: 0,
        right: 0,
        padding: "0 20px",
        fontSize: 11,
        color: "#b1b6bf",
        letterSpacing: 0.3,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        <FileSearchOutlined style={{ fontSize: 10 }} />
        <span>DocumentCheck v1.0</span>
      </div>
      <div>© 2026</div>
    </div>
  );
}

// 已定义但未使用的导入占位符(防止 linter 报未使用)—— AuditOutlined / TeamOutlined 留给后续导航扩展
void AuditOutlined;
void TeamOutlined;
