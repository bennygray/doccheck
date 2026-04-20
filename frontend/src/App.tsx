import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import AdminUsersPage from "./pages/admin/AdminUsersPage";
import AdminRulesPage from "./pages/admin/AdminRulesPage";
import AdminLLMPage from "./pages/admin/AdminLLMPage";
import ProjectListPage from "./pages/projects/ProjectListPage";
import ProjectCreatePage from "./pages/projects/ProjectCreatePage";
import ProjectDetailPage from "./pages/projects/ProjectDetailPage";
import AuditLogPage from "./pages/reports/AuditLogPage";
import ComparePage from "./pages/reports/ComparePage";
import DimensionDetailPage from "./pages/reports/DimensionDetailPage";
import MetaComparePage from "./pages/reports/MetaComparePage";
import PriceComparePage from "./pages/reports/PriceComparePage";
import ReportPage from "./pages/reports/ReportPage";
import TextComparePage from "./pages/reports/TextComparePage";
import SseDemoPage from "./pages/SseDemoPage";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleGuard from "./components/RoleGuard";
import AppLayout from "./components/layout/AppLayout";
import { useAuth } from "./contexts/AuthContext";
import { setOnUnauthorized } from "./services/api";

function App() {
  const { logout } = useAuth();
  const navigate = useNavigate();

  // 注册 401 回调:清 auth + 跳 /login(pendingPath 由 api.ts 写入 localStorage)
  useEffect(() => {
    setOnUnauthorized(() => {
      logout();
      navigate("/login", { replace: true });
    });
    return () => setOnUnauthorized(null);
  }, [logout, navigate]);

  return (
    <Routes>
      {/* 未登录路由:无壳 */}
      <Route path="/login" element={<LoginPage />} />

      {/* 已登录但非主应用路由(改密):保持独立样式,不走 AppLayout */}
      <Route
        path="/change-password"
        element={
          <ProtectedRoute>
            <ChangePasswordPage />
          </ProtectedRoute>
        }
      />

      {/* 主应用:全部套 AppLayout 左栏骨架 */}
      <Route
        element={
          <ProtectedRoute>
            <AppLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/projects" element={<ProjectListPage />} />
        <Route path="/projects/new" element={<ProjectCreatePage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route
          path="/reports/:projectId/:version"
          element={<ReportPage />}
        />
        <Route
          path="/reports/:projectId/:version/dim"
          element={<DimensionDetailPage />}
        />
        <Route
          path="/reports/:projectId/:version/compare"
          element={<ComparePage />}
        />
        <Route
          path="/reports/:projectId/:version/compare/text"
          element={<TextComparePage />}
        />
        <Route
          path="/reports/:projectId/:version/compare/price"
          element={<PriceComparePage />}
        />
        <Route
          path="/reports/:projectId/:version/compare/metadata"
          element={<MetaComparePage />}
        />
        <Route
          path="/reports/:projectId/:version/logs"
          element={<AuditLogPage />}
        />
        <Route
          path="/admin/users"
          element={
            <RoleGuard role="admin">
              <AdminUsersPage />
            </RoleGuard>
          }
        />
        <Route
          path="/admin/rules"
          element={
            <RoleGuard role="admin">
              <AdminRulesPage />
            </RoleGuard>
          }
        />
        <Route
          path="/admin/llm"
          element={
            <RoleGuard role="admin">
              <AdminLLMPage />
            </RoleGuard>
          }
        />
        <Route path="/demo/sse" element={<SseDemoPage />} />
      </Route>

      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}

export default App;
