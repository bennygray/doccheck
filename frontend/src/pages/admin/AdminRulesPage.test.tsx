/**
 * L1 AdminRulesPage 组件测试 (C17)
 *
 * 4 cases: 渲染配置表单 / 保存成功 / 恢复默认 / 非 admin 重定向
 */
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "../../contexts/AuthContext";
import { clearAuthStorage, primeAuthStorage } from "../../contexts/test-utils";
import AdminRulesPage from "./AdminRulesPage";

vi.mock("../../services/api", () => ({
  api: {
    getRules: vi.fn(),
    updateRules: vi.fn(),
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

const mockConfig = {
  dimensions: {
    text_similarity: { enabled: true, weight: 15, llm_enabled: true, threshold: 85 },
    error_consistency: { enabled: true, weight: 20, llm_enabled: true },
    hardware_fingerprint: { enabled: true, weight: 20, llm_enabled: true },
    price_similarity: { enabled: true, weight: 15, llm_enabled: true, threshold: 95 },
    image_reuse: { enabled: true, weight: 13, llm_enabled: true, phash_distance: 5 },
    language_style: { enabled: true, weight: 10, llm_enabled: true, group_threshold: 20 },
    software_metadata: { enabled: true, weight: 7 },
    pricing_pattern: { enabled: true, r_squared_threshold: 0.95 },
    price_ceiling: { enabled: true, variance_threshold: 0.02, range_min: 0.98, range_max: 1.0 },
    operation_time: { enabled: true, window_minutes: 30, min_bidders: 3 },
  },
  risk_levels: { high: 70, medium: 40 },
  doc_role_keywords: { technical: ["技术方案"] },
  hardware_keywords: ["加密锁号"],
  metadata_whitelist: ["Administrator"],
  min_paragraph_length: 50,
  file_retention_days: 90,
};

const mockRulesResponse = {
  config: mockConfig,
  updated_by: null,
  updated_at: null,
};

function renderPage() {
  primeAuthStorage("test-token", adminUser);
  return render(
    <MemoryRouter initialEntries={["/admin/rules"]}>
      <AuthProvider>
        <Routes>
          <Route path="/admin/rules" element={<AdminRulesPage />} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (api.getRules as ReturnType<typeof vi.fn>).mockResolvedValue(mockRulesResponse);
});

afterEach(() => {
  cleanup();
  clearAuthStorage();
});

test("渲染配置表单", async () => {
  renderPage();
  expect(await screen.findByTestId("dimensions-section")).toBeInTheDocument();
  expect(screen.getByTestId("global-section")).toBeInTheDocument();
  expect(screen.getByTestId("save-btn")).toBeInTheDocument();
  expect(screen.getByTestId("restore-btn")).toBeInTheDocument();
});

test("保存成功", async () => {
  (api.updateRules as ReturnType<typeof vi.fn>).mockResolvedValue(mockRulesResponse);

  renderPage();
  await screen.findByTestId("save-btn");

  const user = userEvent.setup();
  await user.click(screen.getByTestId("save-btn"));

  await waitFor(() => {
    expect(api.updateRules).toHaveBeenCalled();
  });

  expect(await screen.findByTestId("success-msg")).toHaveTextContent("保存成功");
});

test("恢复默认", async () => {
  (api.updateRules as ReturnType<typeof vi.fn>).mockResolvedValue(mockRulesResponse);

  renderPage();
  await screen.findByTestId("restore-btn");

  const user = userEvent.setup();
  await user.click(screen.getByTestId("restore-btn"));

  await waitFor(() => {
    expect(api.updateRules).toHaveBeenCalledWith({ restore_defaults: true });
  });

  expect(await screen.findByTestId("success-msg")).toHaveTextContent("已恢复默认配置");
});

test("RoleGuard 非 admin 重定向", async () => {
  const { default: RoleGuard } = await import("../../components/RoleGuard");
  primeAuthStorage("test-token", reviewerUser);
  render(
    <MemoryRouter initialEntries={["/admin/rules"]}>
      <AuthProvider>
        <Routes>
          <Route
            path="/admin/rules"
            element={
              <RoleGuard role="admin">
                <AdminRulesPage />
              </RoleGuard>
            }
          />
          <Route path="/projects" element={<div data-testid="projects-redirect">Redirected</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
  expect(await screen.findByTestId("projects-redirect")).toBeInTheDocument();
});
