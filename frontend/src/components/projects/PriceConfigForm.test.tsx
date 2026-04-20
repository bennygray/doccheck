/**
 * L1: PriceConfigForm (C4 file-upload §10.8)
 *
 * 覆盖:首次 GET=null 显示默认 → 填表 PUT → 显示已保存 / GET 已有数据回显。
 * 注:已迁移到 antd Select / Checkbox;getByTestId 返回 wrapper,内部通过
 *   .ant-select-selector + findByText 打开下拉选项。
 */
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PriceConfigForm from "./PriceConfigForm";

vi.mock("../../services/api", () => ({
  api: {
    getPriceConfig: vi.fn(),
    putPriceConfig: vi.fn(),
  },
}));

import { api } from "../../services/api";

async function pickAntdSelect(testid: string, optionText: string) {
  const wrapper = screen.getByTestId(testid);
  const selector = wrapper.querySelector(".ant-select-selector")!;
  fireEvent.mouseDown(selector);
  // 下拉展开后,option 落在 portal 的 .ant-select-item 容器里;已选中的值
  // 也会以 .ant-select-selection-item 形式出现在 selector 中 → 取 option 那一个
  await screen.findAllByText(optionText);
  const opts = Array.from(
    document.querySelectorAll(".ant-select-item-option"),
  ).filter((el) => el.textContent === optionText);
  fireEvent.click(opts[opts.length - 1]);
}

describe("PriceConfigForm", () => {
  it("首次 GET=null,默认值 → 填表保存触发 PUT", async () => {
    (api.getPriceConfig as ReturnType<typeof vi.fn>).mockResolvedValueOnce(null);
    (api.putPriceConfig as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      project_id: 1,
      currency: "USD",
      tax_inclusive: false,
      unit_scale: "wan_yuan",
      updated_at: "2026-04-14T00:00:00Z",
    });

    const user = userEvent.setup();
    render(<PriceConfigForm projectId={1} />);
    await waitFor(() =>
      expect(screen.getByTestId("price-config-form")).toBeInTheDocument(),
    );

    await pickAntdSelect("price-config-currency", "USD");
    // 取消含税 checkbox(默认 true,点击变 false)
    const taxInput = screen
      .getByTestId("price-config-tax")
      .querySelector('input[type="checkbox"]')!;
    await user.click(taxInput);
    await pickAntdSelect("price-config-unit", "万元");
    await user.click(screen.getByTestId("price-config-save"));

    await waitFor(() => expect(api.putPriceConfig).toHaveBeenCalledTimes(1));
    expect(api.putPriceConfig).toHaveBeenCalledWith(1, {
      currency: "USD",
      tax_inclusive: false,
      unit_scale: "wan_yuan",
    });
  });

  it("GET 已有数据回显字段", async () => {
    (api.getPriceConfig as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      project_id: 2,
      currency: "EUR",
      tax_inclusive: true,
      unit_scale: "fen",
      updated_at: "2026-04-14T00:00:00Z",
    });

    render(<PriceConfigForm projectId={2} />);
    await waitFor(() =>
      expect(screen.getByTestId("price-config-form")).toBeInTheDocument(),
    );
    // antd Select 回显:selector 内有 ant-select-selection-item 显示当前值
    const currencyWrapper = screen.getByTestId("price-config-currency");
    expect(currencyWrapper.textContent).toContain("EUR");

    const taxInput = screen
      .getByTestId("price-config-tax")
      .querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(taxInput.checked).toBe(true);

    const unitWrapper = screen.getByTestId("price-config-unit");
    expect(unitWrapper.textContent).toContain("分");

    expect(screen.getByText("更新")).toBeInTheDocument();
  });
});
