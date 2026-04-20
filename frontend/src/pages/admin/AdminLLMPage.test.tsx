/**
 * L1: AdminLLMPage (admin-llm-config)
 *
 * 覆盖:
 *  - 加载时 GET 回显脱敏 api_key + source 提示
 *  - 保存点击调用 updateLLMConfig(空 apiKey 不传)
 *  - 测试连接按钮调 testLLMConnection 并展示结果
 *  - 恢复默认重置表单字段
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App as AntdApp } from "antd";
import { AuthProvider } from "../../contexts/AuthContext";
import { clearAuthStorage, primeAuthStorage } from "../../contexts/test-utils";
import AdminLLMPage from "./AdminLLMPage";

vi.mock("../../services/api", () => ({
  api: {
    getLLMConfig: vi.fn(),
    updateLLMConfig: vi.fn(),
    testLLMConnection: vi.fn(),
  },
  ApiError: class ApiError extends Error {
    status: number;
    constructor(status: number, msg = "") {
      super(msg);
      this.status = status;
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
    <MemoryRouter>
      <AuthProvider>
        <AntdApp>
          <AdminLLMPage />
        </AntdApp>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("AdminLLMPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });
  afterEach(() => {
    clearAuthStorage();
  });

  it("加载时 GET 回显脱敏 api_key 和 source 提示", async () => {
    (api.getLLMConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: "dashscope",
      api_key_masked: "sk-****1234",
      model: "qwen-plus",
      base_url: null,
      timeout_s: 30,
      source: "db",
    });

    renderPage();

    // 等待脱敏 key 出现在 placeholder 或 extra 文案
    await waitFor(() => {
      expect(screen.getByText(/sk-\*\*\*\*1234/)).toBeInTheDocument();
    });
    // source=db 应显示"已从后台保存"
    expect(screen.getByText(/已从后台保存/)).toBeInTheDocument();
  });

  it("保存点击 - 空 apiKey 不传给后端", async () => {
    (api.getLLMConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: "openai",
      api_key_masked: "sk-****abcd",
      model: "gpt-4o-mini",
      base_url: null,
      timeout_s: 30,
      source: "db",
    });
    (api.updateLLMConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: "openai",
      api_key_masked: "sk-****abcd",
      model: "gpt-4o-mini",
      base_url: null,
      timeout_s: 30,
      source: "db",
    });

    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("llm-save-btn");

    await user.click(screen.getByTestId("llm-save-btn"));

    await waitFor(() => {
      expect(api.updateLLMConfig).toHaveBeenCalledTimes(1);
    });
    const payload = (api.updateLLMConfig as ReturnType<typeof vi.fn>).mock.calls[0][0];
    // 空 apiKey 不应出现在 payload
    expect(payload.api_key).toBeUndefined();
    expect(payload.provider).toBe("openai");
    expect(payload.model).toBe("gpt-4o-mini");
  });

  it("测试连接按钮调用 API 并渲染 ok 结果", async () => {
    (api.getLLMConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: "dashscope",
      api_key_masked: "sk-****1234",
      model: "qwen-plus",
      base_url: null,
      timeout_s: 30,
      source: "db",
    });
    (api.testLLMConnection as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      latency_ms: 120,
      error: null,
    });

    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("llm-test-btn");

    await user.click(screen.getByTestId("llm-test-btn"));
    await waitFor(() => {
      expect(api.testLLMConnection).toHaveBeenCalled();
    });
    const result = await screen.findByTestId("llm-test-result");
    expect(result).toHaveTextContent(/连接成功/);
    expect(result).toHaveTextContent(/120/);
  });

  it("测试连接失败显示错误 Alert", async () => {
    (api.getLLMConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: "dashscope",
      api_key_masked: "",
      model: "qwen-plus",
      base_url: null,
      timeout_s: 30,
      source: "default",
    });
    (api.testLLMConnection as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: false,
      latency_ms: 3020,
      error: "[timeout] LLM 调用超时",
    });

    const user = userEvent.setup();
    renderPage();
    await screen.findByTestId("llm-test-btn");

    await user.click(screen.getByTestId("llm-test-btn"));
    const result = await screen.findByTestId("llm-test-result");
    expect(result).toHaveTextContent(/连接失败/);
    expect(result).toHaveTextContent(/timeout/);
  });

  it("恢复默认按钮重置表单", async () => {
    (api.getLLMConfig as ReturnType<typeof vi.fn>).mockResolvedValue({
      provider: "openai",
      api_key_masked: "sk-****xxxx",
      model: "gpt-4o-mini",
      base_url: null,
      timeout_s: 60,
      source: "db",
    });

    renderPage();
    await screen.findByTestId("llm-restore-btn");

    fireEvent.click(screen.getByTestId("llm-restore-btn"));

    // 恢复后 provider select 显示 "阿里百炼"(dashscope 默认的 label)
    await waitFor(() => {
      expect(screen.getByText(/阿里百炼/)).toBeInTheDocument();
    });
    // timeout InputNumber 的 spinbutton 值应为 30
    const timeoutInput = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(timeoutInput.value).toBe("30");
  });
});
