/**
 * L1: ProjectListPage (C3 project-mgmt)
 *
 * 覆盖:空态渲染 / 有数据渲染 / 筛选触发 query 变化 / 搜索触发 query 变化。
 * api 通过 vi.mock 替换,避免真实 fetch。
 *
 * 注:页面 mount 时会发 5 次 listProjects(1 主列表 + 4 stat 卡),
 * 所以这里用 mockResolvedValue(默认值,所有后续调用都命中)+ 按调用参数断言,
 * 而不是断言 "调用了 N 次"。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

type ListProjectsArg = {
  page?: number;
  size?: number;
  status?: string;
  risk_level?: string;
  search?: string;
};

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

/** 主列表调用 = 不带 size=1 的那次 */
function mainListCalls(): ListProjectsArg[] {
  return (api.listProjects as ReturnType<typeof vi.fn>).mock.calls
    .map((c) => c[0] as ListProjectsArg)
    .filter((arg) => arg?.size !== 1);
}

describe("ProjectListPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // 默认返回空集,覆盖 stat 面板的 4 次并发 + 列表的 1 次
    (api.listProjects as ReturnType<typeof vi.fn>).mockResolvedValue({
      items: [],
      total: 0,
      page: 1,
      size: 12,
    });
  });
  afterEach(() => {
    clearAuthStorage();
  });

  it("空数据时显示空态引导", async () => {
    renderPage();
    expect(await screen.findByTestId("empty-state")).toBeInTheDocument();
    expect(screen.queryByTestId("project-grid")).not.toBeInTheDocument();
  });

  it("有数据时渲染卡片网格", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>).mockImplementation(
      async (arg: ListProjectsArg) => {
        // stat 卡请求 size=1 → 返空即可;主列表返两条
        if (arg?.size === 1) {
          return { items: [], total: 0, page: 1, size: 1 };
        }
        return {
          items: [mkItem(1, "项目 A"), mkItem(2, "项目 B")],
          total: 2,
          page: 1,
          size: 12,
        };
      },
    );
    renderPage();
    expect(await screen.findByTestId("project-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("project-card-2")).toBeInTheDocument();
    expect(screen.queryByTestId("empty-state")).not.toBeInTheDocument();
  });

  it("点击状态筛选触发新 query", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("empty-state");

    const initialMainCalls = mainListCalls().length;

    // antd Select 用 mouseDown 开下拉(非 click);选项渲染在 portal
    const statusWrapper = screen.getByTestId("filter-status");
    const selector = statusWrapper.querySelector(".ant-select-selector")!;
    fireEvent.mouseDown(selector);
    const option = await screen.findByText("草稿");
    await user.click(option);

    await waitFor(() => {
      const calls = mainListCalls();
      expect(calls.length).toBeGreaterThan(initialMainCalls);
      expect(calls.some((c) => c.status === "draft")).toBe(true);
    });
  });

  it("提交搜索触发新 query 且 page 重置为 1", async () => {
    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("empty-state");

    const initialMainCalls = mainListCalls().length;

    // antd Input.Search 的 testid 落在包裹 div 上,真正的输入框在内部
    const searchWrapper = screen.getByTestId("search-input");
    const searchInput = searchWrapper.querySelector("input")!;
    await user.type(searchInput, "高速");
    await user.click(screen.getByTestId("search-submit"));

    await waitFor(() => {
      const calls = mainListCalls();
      expect(calls.length).toBeGreaterThan(initialMainCalls);
      expect(calls.some((c) => c.search === "高速" && c.page === 1)).toBe(true);
    });
  });

  // honest-detection-results: risk_level indeterminate + 回归
  it("渲染 indeterminate 项目显示'证据不足'灰色 Tag", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>).mockImplementation(
      async (arg: ListProjectsArg) => {
        if (arg?.size === 1) {
          return { items: [], total: 0, page: 1, size: 1 };
        }
        return {
          items: [
            mkItem(10, "全零信号项目", {
              // 默认 tab 是"active",用 draft 让 card 渲染;risk_level 与 status 语义正交,
              // 测试只关心 Tag 显示正确
              risk_level: "indeterminate",
            }),
          ],
          total: 1,
          page: 1,
          size: 12,
        };
      },
    );
    renderPage();
    await screen.findByTestId("project-card-10");
    expect(screen.getByText("证据不足")).toBeInTheDocument();
  });

  it("历史 low/medium/high 项目渲染不变(回归)", async () => {
    (api.listProjects as ReturnType<typeof vi.fn>).mockImplementation(
      async (arg: ListProjectsArg) => {
        if (arg?.size === 1) {
          return { items: [], total: 0, page: 1, size: 1 };
        }
        return {
          items: [
            mkItem(21, "项目L", { risk_level: "low" }),
            mkItem(22, "项目M", { risk_level: "medium" }),
            mkItem(23, "项目H", { risk_level: "high" }),
          ],
          total: 3,
          page: 1,
          size: 12,
        };
      },
    );
    renderPage();
    await screen.findByTestId("project-card-21");
    // 各档 Tag 文案都存在(Tag 里才有,项目名避开这些词防误匹配)
    expect(screen.getByText("低风险")).toBeInTheDocument();
    expect(screen.getByText("中风险")).toBeInTheDocument();
    expect(screen.getByText("高风险")).toBeInTheDocument();
    expect(screen.queryByText("证据不足")).not.toBeInTheDocument();
  });
});
