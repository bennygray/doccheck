/**
 * ProtectedRoute (C2 auth)
 *
 * - 未登录 → 重定向 /login(把当前路径写入 pendingPath,登录后恢复)
 * - 登录但 must_change_password=true 且当前非 /change-password → 强制跳 /change-password
 * - hydration 未完成时渲染 null,避免闪跳
 */
import { Navigate, useLocation } from "react-router-dom";
import { authStorage, useAuth } from "../contexts/AuthContext";
import type { ReactNode } from "react";

export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { hydrated, token, user } = useAuth();
  const location = useLocation();

  if (!hydrated) return null;

  if (!token || !user) {
    // 保留用户原本的目标路径,登录成功后可恢复
    // 排除 /login 与 /change-password:前者不是保护路径,后者是改密流程的中转页,
    // 记到 pendingPath 会让下次登录跳错地方
    const path = location.pathname;
    if (path !== "/login" && path !== "/change-password") {
      authStorage.setPendingPath(path + location.search);
    }
    return <Navigate to="/login" replace />;
  }

  if (user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }

  return <>{children}</>;
}
