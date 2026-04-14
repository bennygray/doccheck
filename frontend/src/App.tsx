import { Navigate, Route, Routes, useNavigate } from "react-router-dom";
import { useEffect } from "react";
import LoginPage from "./pages/LoginPage";
import ChangePasswordPage from "./pages/ChangePasswordPage";
import ProjectsPlaceholderPage from "./pages/ProjectsPlaceholderPage";
import SseDemoPage from "./pages/SseDemoPage";
import ProtectedRoute from "./components/ProtectedRoute";
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
            <ProjectsPlaceholderPage />
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
