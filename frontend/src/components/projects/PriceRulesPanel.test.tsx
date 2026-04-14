/**
 * L1: PriceRulesPanel (C5 §10.2)
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PriceRulesPanel from "./PriceRulesPanel";

vi.mock("../../services/api", () => ({
  api: {
    listPriceRules: vi.fn(),
    putPriceRuleById: vi.fn(),
  },
}));

import { api } from "../../services/api";

const MOCK_RULE = {
  id: 11,
  project_id: 1,
  sheet_name: "报价清单",
  header_row: 2,
  column_mapping: {
    code_col: "A",
    name_col: "B",
    unit_col: "C",
    qty_col: "D",
    unit_price_col: "E",
    total_price_col: "F",
    skip_cols: [],
  },
  created_by_llm: true,
  confirmed: true,
  created_at: "2026-04-14T00:00:00Z",
  updated_at: "2026-04-14T00:00:00Z",
};

describe("PriceRulesPanel", () => {
  it("空规则显示空态", async () => {
    (api.listPriceRules as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    render(<PriceRulesPanel projectId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("price-rules-empty")).toBeInTheDocument(),
    );
  });

  it("渲染 LLM 识别规则 + 列映射", async () => {
    (api.listPriceRules as ReturnType<typeof vi.fn>).mockResolvedValueOnce([
      MOCK_RULE,
    ]);
    render(<PriceRulesPanel projectId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("price-rules-panel")).toBeInTheDocument(),
    );
    expect(screen.getByText(/报价清单/)).toBeInTheDocument();
    const codeInput = screen.getByTestId(
      "rule-11-code_col",
    ) as HTMLInputElement;
    expect(codeInput.value).toBe("A");
  });

  it("修改列映射并点提交触发 putPriceRuleById", async () => {
    (api.listPriceRules as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce([MOCK_RULE])
      .mockResolvedValueOnce([{ ...MOCK_RULE, created_by_llm: false }]);
    (api.putPriceRuleById as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ...MOCK_RULE,
      created_by_llm: false,
    });
    const user = userEvent.setup();
    render(<PriceRulesPanel projectId={1} />);
    await waitFor(() => screen.getByTestId("price-rules-panel"));

    const qtyInput = screen.getByTestId("rule-11-qty_col");
    await user.clear(qtyInput);
    await user.type(qtyInput, "X");

    await user.click(screen.getByTestId("rule-11-submit"));

    await waitFor(() =>
      expect(api.putPriceRuleById).toHaveBeenCalledWith(
        1,
        11,
        expect.objectContaining({
          column_mapping: expect.objectContaining({ qty_col: "X" }),
          created_by_llm: false,
          confirmed: true,
        }),
      ),
    );
  });

  it("listPriceRules 失败显示错误", async () => {
    (api.listPriceRules as ReturnType<typeof vi.fn>).mockRejectedValueOnce(
      new Error("boom"),
    );
    render(<PriceRulesPanel projectId={1} />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("加载失败"),
    );
  });
});
