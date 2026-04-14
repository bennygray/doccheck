/**
 * RoleGuard (C2 auth)
 *
 * 在 ProtectedRoute 之上再校角色;角色不符 → /projects。
 */
import { Navigate } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import type { ReactNode } from "react";

export default function RoleGuard({
  role,
  children,
}: {
  role: "admin" | "reviewer";
  children: ReactNode;
}) {
  const { user } = useAuth();
  if (!user || user.role !== role) {
    return <Navigate to="/projects" replace />;
  }
  return <>{children}</>;
}
