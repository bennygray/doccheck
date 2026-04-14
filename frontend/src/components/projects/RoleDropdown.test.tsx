/**
 * L1: RoleDropdown (C5 §10.1)
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import RoleDropdown from "./RoleDropdown";

vi.mock("../../services/api", () => ({
  api: {
    patchDocumentRole: vi.fn(),
  },
}));

import { api } from "../../services/api";

describe("RoleDropdown", () => {
  it("渲染 9 种角色选项", () => {
    render(
      <RoleDropdown documentId={1} role="technical" confidence="high" />,
    );
    const select = screen.getByRole("combobox", { name: /修改文档角色/ });
    const options = Array.from(select.querySelectorAll("option"));
    const values = options.map((o) => o.getAttribute("value"));
    for (const v of [
      "technical",
      "construction",
      "pricing",
      "unit_price",
      "bid_letter",
      "qualification",
      "company_intro",
      "authorization",
      "other",
    ]) {
      expect(values).toContain(v);
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
    const user = userEvent.setup();
    render(
      <RoleDropdown
        documentId={7}
        role="technical"
        confidence="high"
        onChanged={onChanged}
      />,
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: /修改文档角色/ }),
      "pricing",
    );

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
    const user = userEvent.setup();
    render(
      <RoleDropdown
        documentId={5}
        role="technical"
        confidence="high"
        onChanged={onChanged}
      />,
    );
    await user.selectOptions(
      screen.getByRole("combobox", { name: /修改文档角色/ }),
      "other",
    );
    await waitFor(() =>
      expect(onChanged).toHaveBeenCalledWith("other", "文档角色已修改..."),
    );
  });
});
