import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import AdminUsersPage from "./pages/admin/AdminUsersPage";
import AdminRulesPage from "./pages/admin/AdminRulesPage";
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
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/admin/users"
        element={
          <ProtectedRoute>
            <RoleGuard role="admin">
              <AdminUsersPage />
            </RoleGuard>
          </ProtectedRoute>
        }
      />
      <Route
        path="/admin/rules"
        element={
          <ProtectedRoute>
            <RoleGuard role="admin">
              <AdminRulesPage />
            </RoleGuard>
          </ProtectedRoute>
        }
      />
      <Route
        path="/change-password"
        element={
          <ProtectedRoute>
            <ChangePasswordPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects"
        element={
          <ProtectedRoute>
            <ProjectListPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/new"
        element={
          <ProtectedRoute>
            <ProjectCreatePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/projects/:id"
        element={
          <ProtectedRoute>
            <ProjectDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version"
        element={
          <ProtectedRoute>
            <ReportPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version/dim"
        element={
          <ProtectedRoute>
            <DimensionDetailPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version/compare"
        element={
          <ProtectedRoute>
            <ComparePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version/compare/text"
        element={
          <ProtectedRoute>
            <TextComparePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version/compare/price"
        element={
          <ProtectedRoute>
            <PriceComparePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version/compare/metadata"
        element={
          <ProtectedRoute>
            <MetaComparePage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/reports/:projectId/:version/logs"
        element={
          <ProtectedRoute>
            <AuditLogPage />
          </ProtectedRoute>
        }
      />
      <Route
        path="/demo/sse"
        element={
          <ProtectedRoute>
            <SseDemoPage />
          </ProtectedRoute>
        }
      />
      <Route path="/" element={<Navigate to="/projects" replace />} />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}

export default App;
