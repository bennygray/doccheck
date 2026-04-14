/**
 * L1: ProjectListPage (C3 project-mgmt)
 *
 * 覆盖:空态渲染 / 有数据渲染 / 筛选触发 query 变化 / 搜索触发 query 变化。
 * api 通过 vi.mock 替换,避免真实 fetch。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { AuthProvider } from "../../contexts/AuthContext";
import { clearAuthStorage, primeAuthStorage } from "../../contexts/test-utils";
import ProjectListPage from "./ProjectListPage";

vi.mock("../../services/api", () => ({
  api: {
    listProjects: vi.fn(),
    deleteProject: vi.fn(),
    logout: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    detail: unknown;
    constructor(status: number, detail: unknown) {
      super(`API error ${status}`);
      this.status = status;
      this.detail = detail;
    }
  },
}));

import { api } from "../../services/api";

const adminUser = {
  id: 1,
  username: "admin",
  role: "admin",
  is_active: true,
  must_change_password: false,
};

function renderPage() {
  primeAuthStorage("tok", adminUser);
  return render(
    <MemoryRouter initialEntries={["/projects"]}>
      <AuthProvider>
        <ProjectListPage />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const mkItem = (id: number, name: string, extra: Partial<Record<string, unknown>> = {}) => ({
  id,
  name,
  bid_code: null,
  max_price: null,
  description: null,
  status: "draft",
  risk_level: null,
  owner_id: 1,
  created_at: "2026-04-14T00:00:00Z",
  updated_at: "2026-04-14T00:00:00Z",
  deleted_at: null,
  ...extra,
});

describe("ProjectListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    clearAuthStorage();
  });

  it("空数据时显示空态引导", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [],
      total: 0,
      page: 1,
      size: 12,
    });
    renderPage();
    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("project-grid")).not.toBeInTheDocument();
  });

  it("有数据时渲染卡片网格", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      items: [mkItem(1, "项目 A"), mkItem(2, "项目 B")],
      total: 2,
      page: 1,
      size: 12,
    });
    renderPage();
    expect(await screen.findByTestId("project-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("project-card-2")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });

  it("点击状态筛选触发新 query", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, size: 12 })
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, size: 12 });

    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("empty-state");

    await user.selectOptions(screen.getByTestId("filter-status"), "draft");

    await waitFor(() => {
      expect(api.listProjects).toHaveBeenCalledTimes(2);
    });
    const lastCall = (api.listProjects as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
    expect(lastCall[0]).toMatchObject({ status: "draft", page: 1 });
  });

  it("提交搜索触发新 query 且 page 重置为 1", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, size: 12 })
      .mockResolvedValueOnce({ items: [], total: 0, page: 1, size: 12 });

    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("empty-state");

    await user.type(screen.getByTestId("search-input"), "高速");
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() => {
      expect(api.listProjects).toHaveBeenCalledTimes(2);
    });
    const lastCall = (api.listProjects as ReturnType<typeof vi.fn>).mock.calls.at(-1)!;
    expect(lastCall[0]).toMatchObject({ search: "高速", page: 1 });
  });
});
