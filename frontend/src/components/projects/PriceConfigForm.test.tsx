/**
 * L1: PriceConfigForm (C4 file-upload §10.8)
 *
 * 覆盖:首次 GET=null 显示默认 → 填表 PUT → 显示已保存 / GET 已有数据回显。
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PriceConfigForm from "./PriceConfigForm";

vi.mock("../../services/api", () => ({
  api: {
    getPriceConfig: vi.fn(),
    putPriceConfig: vi.fn(),
  },
}));

import { api } from "../../services/api";

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

    await user.selectOptions(screen.getByTestId("price-config-currency"), "USD");
    await user.click(screen.getByTestId("price-config-tax")); // 取消含税
    await user.selectOptions(screen.getByTestId("price-config-unit"), "wan_yuan");
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
    expect(
      (screen.getByTestId("price-config-currency") as HTMLSelectElement).value,
    ).toBe("EUR");
    expect(
      (screen.getByTestId("price-config-tax") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByTestId("price-config-unit") as HTMLSelectElement).value,
    ).toBe("fen");
    expect(screen.getByText("更新")).toBeInTheDocument();
  });
});
