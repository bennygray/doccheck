/**
 * L1 AdminUsersPage 组件测试 (C17)
 *
 * 4 cases: 渲染用户列表 / 创建用户成功 / 禁用开关 / 非 admin 重定向
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../contexts/AuthContext";
import { clearAuthStorage, primeAuthStorage } from "../../contexts/test-utils";
import AdminUsersPage from "./AdminUsersPage";

vi.mock("../../services/api", () => ({
  api: {
    getUsers: vi.fn(),
    createUser: vi.fn(),
    updateUser: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(msg: string, status = 400) {
      super(msg);
      this.status = status;
    }
  },
}));

import { api } from "../../services/api";

const adminUser = {
  id: 1,
  username: "admin",
  role: "admin" as const,
  is_active: true,
  must_change_password: false,
};

const reviewerUser = {
  id: 2,
  username: "reviewer1",
  role: "reviewer" as const,
  is_active: true,
  must_change_password: false,
};

const mockUsers = [
  { ...adminUser, created_at: "2026-01-01T00:00:00Z" },
  { ...reviewerUser, created_at: "2026-01-02T00:00:00Z" },
];

function renderPage() {
  primeAuthStorage("test-token", adminUser);
  return render(
    <MemoryRouter initialEntries={["/admin/users"]}>
      <AuthProvider>
        <Routes>
          <Route path="/admin/users" element={<AdminUsersPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.getUsers as ReturnType<typeof vi.fn>).mockResolvedValue(mockUsers);
});

afterEach(() => {
  cleanup();
  clearAuthStorage();
});

test("渲染用户列表", async () => {
  renderPage();
  expect(await screen.findByTestId("users-table")).toBeInTheDocument();
  expect(screen.getByText("admin")).toBeInTheDocument();
  expect(screen.getByText("reviewer1")).toBeInTheDocument();
});

test(
  "创建用户成功",
  async () => {
    (api.createUser as ReturnType<typeof vi.fn>).mockResolvedValue({
      id: 3,
      username: "newuser",
      role: "reviewer",
      is_active: true,
      must_change_password: true,
      created_at: "2026-01-03T00:00:00Z",
    });

    renderPage();
    await screen.findByTestId("users-table");

    // fix-admin-users-page-flaky-test:
    // - delay:null 移除 keystroke 间 microtask tick(主方案 D1)
    // - test-level timeout 15000 兜底全量跑下 vitest + jsdom + antd 累积负载
    //   (fallback D2 实测触发:delay:null 独立 3/3 fail,加 timeout 后稳定绿)
    const user = userEvent.setup({ delay: null });
    await user.click(screen.getByTestId("create-user-btn"));
    await user.type(screen.getByTestId("input-username"), "newuser");
    await user.type(screen.getByTestId("input-password"), "Test1234");
    await user.click(screen.getByText("确认创建"));

    await waitFor(() => {
      expect(api.createUser).toHaveBeenCalledWith({
        username: "newuser",
        password: "Test1234",
        role: "reviewer",
      });
    });
  },
  15000,
);

test("禁用开关", async () => {
  (api.updateUser as ReturnType<typeof vi.fn>).mockResolvedValue({
    ...mockUsers[1],
    is_active: false,
  });

  renderPage();
  await screen.findByTestId("users-table");

  const user = userEvent.setup();
  await user.click(screen.getByTestId(`toggle-active-${reviewerUser.id}`));

  await waitFor(() => {
    expect(api.updateUser).toHaveBeenCalledWith(reviewerUser.id, {
      is_active: false,
    });
  });
});

test("RoleGuard 非 admin 重定向", async () => {
  // RoleGuard 已在 C2 测试覆盖，这里验证组件存在即可
  const { default: RoleGuard } = await import("../../components/RoleGuard");
  primeAuthStorage("test-token", reviewerUser);
  render(
    <MemoryRouter initialEntries={["/admin/users"]}>
      <AuthProvider>
        <Routes>
          <Route
            path="/admin/users"
            element={
              <RoleGuard role="admin">
                <AdminUsersPage />
              </RoleGuard>
            }
          />
          <Route path="/projects" element={<div data-testid="projects-redirect">Redirected</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
  // RoleGuard 在 hydration 前 user=null → redirect;hydration 后 user.role=reviewer → redirect
  // 两种情况都去 /projects
  expect(await screen.findByTestId("projects-redirect")).toBeInTheDocument();
});
