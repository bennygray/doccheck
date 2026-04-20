/**
 * L1: RoleDropdown (C5 §10.1)
 *
 * antd 化后:select 不再是原生 <select>,是 antd Select;
 * 测试改用 fireEvent.mouseDown 开下拉 + findByText 选项。
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import RoleDropdown from "./RoleDropdown";

vi.mock("../../services/api", () => ({
  api: {
    patchDocumentRole: vi.fn(),
  },
}));

import { api } from "../../services/api";

async function pickAntdSelect(combobox: HTMLElement, optionText: string) {
  const wrapper = combobox.closest(".ant-select") as HTMLElement;
  const selector = wrapper.querySelector(".ant-select-selector")!;
  fireEvent.mouseDown(selector);
  // 已选中的值也会在 selector 里显示同样文本 → 精确取 .ant-select-item-option
  await screen.findAllByText(optionText);
  const opts = Array.from(
    document.querySelectorAll(".ant-select-item-option"),
  ).filter((el) => el.textContent === optionText);
  fireEvent.click(opts[opts.length - 1]);
}

describe("RoleDropdown", () => {
  it("渲染 9 种角色选项", async () => {
    render(
      <RoleDropdown documentId={1} role="technical" confidence="high" />,
    );
    const combobox = screen.getByRole("combobox", { name: /修改文档角色/ });
    const wrapper = combobox.closest(".ant-select") as HTMLElement;
    const selector = wrapper.querySelector(".ant-select-selector")!;
    fireEvent.mouseDown(selector);
    // 下拉展开后 .ant-select-item-option 包含全部 9 个
    await screen.findAllByText("技术方案");
    const opts = Array.from(
      document.querySelectorAll(".ant-select-item-option"),
    ).map((el) => el.textContent);
    for (const label of [
      "技术方案",
      "施工组织",
      "报价清单",
      "综合单价",
      "投标函",
      "资质证明",
      "企业介绍",
      "授权委托",
      "其他",
    ]) {
      expect(opts).toContain(label);
    }
  });

  it("低置信度显示'待确认'徽章", () => {
    render(<RoleDropdown documentId={1} role="technical" confidence="low" />);
    expect(screen.getByText("待确认")).toBeInTheDocument();
  });

  it("high 置信度不显示'待确认'", () => {
    render(<RoleDropdown documentId={1} role="technical" confidence="high" />);
    expect(screen.queryByText("待确认")).not.toBeInTheDocument();
  });

  it("点击下拉修改 → 调 patchDocumentRole + onChanged", async () => {
    (api.patchDocumentRole as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 7,
      file_role: "pricing",
      role_confidence: "user",
      warn: null,
    });
    const onChanged = vi.fn();
    render(
      <RoleDropdown
        documentId={7}
        role="technical"
        confidence="high"
        onChanged={onChanged}
      />,
    );

    const combobox = screen.getByRole("combobox", { name: /修改文档角色/ });
    await pickAntdSelect(combobox, "报价清单");

    await waitFor(() =>
      expect(api.patchDocumentRole).toHaveBeenCalledWith(7, "pricing"),
    );
    expect(onChanged).toHaveBeenCalledWith("pricing", null);
  });

  it("completed 项目场景:warn 传给 onChanged", async () => {
    (api.patchDocumentRole as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      id: 5,
      file_role: "other",
      role_confidence: "user",
      warn: "文档角色已修改...",
    });
    const onChanged = vi.fn();
    render(
      <RoleDropdown
        documentId={5}
        role="technical"
        confidence="high"
        onChanged={onChanged}
      />,
    );
    const combobox = screen.getByRole("combobox", { name: /修改文档角色/ });
    await pickAntdSelect(combobox, "其他");

    await waitFor(() =>
      expect(onChanged).toHaveBeenCalledWith("other", "文档角色已修改..."),
    );
  });
});
