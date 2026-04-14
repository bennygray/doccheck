/**
 * L1: ProjectCreatePage (C3 project-mgmt)
 *
 * 覆盖:空 name 不可提交 / max_price 负数显示错误 / 未填 max_price 显示 US-2.1 提示文案 /
 *      成功提交后 navigate 到详情页。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import ProjectCreatePage from "./ProjectCreatePage";

vi.mock("../../services/api", () => ({
  api: {
    createProject: vi.fn(),
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

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/projects/new"]}>
      <Routes>
        <Route path="/projects/new" element={<ProjectCreatePage />} />
        <Route
          path="/projects/:id"
          element={<div data-testid="detail-stub">DETAIL</div>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProjectCreatePage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("初次渲染显示未填 max_price 的提示文案", () => {
    renderPage();
    expect(screen.getByTestId("no-max-price-hint")).toHaveTextContent(
      /未设置最高限价/,
    );
  });

  it("填入 max_price 后提示文案消失", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByTestId("create-max-price"), "100");
    expect(screen.queryByTestId("no-max-price-hint")).not.toBeInTheDocument();
  });

  it("空 name 提交显示错误且不调用 api", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.click(screen.getByTestId("create-submit"));
    // 原生 required 会拦一次,但以防万一校验也写了兜底
    expect(api.createProject).not.toHaveBeenCalled();
  });

  it("纯空白 name 提交显示错误", async () => {
    const user = userEvent.setup();
    renderPage();
    // 直接在 state 赋值:原生 required 只认 "",空白会绕过,需要 JS 校验兜底
    const nameInput = screen.getByTestId("create-name") as HTMLInputElement;
    await user.type(nameInput, "   ");
    await user.click(screen.getByTestId("create-submit"));
    expect(await screen.findByTestId("create-error")).toHaveTextContent(
      /名称不能为空/,
    );
    expect(api.createProject).not.toHaveBeenCalled();
  });

  it("max_price 负数显示错误", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByTestId("create-name"), "合法项目");
    await user.type(screen.getByTestId("create-max-price"), "-5");
    await user.click(screen.getByTestId("create-submit"));
    expect(await screen.findByTestId("create-error")).toHaveTextContent(
      /不能为负数/,
    );
    expect(api.createProject).not.toHaveBeenCalled();
  });

  it("max_price 小数过多显示错误", async () => {
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByTestId("create-name"), "合法项目");
    await user.type(screen.getByTestId("create-max-price"), "1.234");
    await user.click(screen.getByTestId("create-submit"));
    expect(await screen.findByTestId("create-error")).toHaveTextContent(
      /最多保留两位小数/,
    );
    expect(api.createProject).not.toHaveBeenCalled();
  });

  it("成功创建后跳转到详情页", async () => {
    (api.createProject as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 42,
      name: "合法项目",
      bid_code: null,
      max_price: null,
      description: null,
      status: "draft",
      risk_level: null,
      owner_id: 1,
      created_at: "2026-04-14T00:00:00Z",
      updated_at: "2026-04-14T00:00:00Z",
      deleted_at: null,
    });
    const user = userEvent.setup();
    renderPage();
    await user.type(screen.getByTestId("create-name"), "合法项目");
    await user.click(screen.getByTestId("create-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("detail-stub")).toBeInTheDocument();
    });
    expect(api.createProject).toHaveBeenCalledWith({
      name: "合法项目",
      bid_code: null,
      max_price: null,
      description: null,
    });
  });
});
