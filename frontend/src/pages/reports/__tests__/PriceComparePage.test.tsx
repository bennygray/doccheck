import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PriceComparePage from "../PriceComparePage";
import { api } from "../../../services/api";
import type { PriceCompareResponse } from "../../../types";

const renderAt = (path: string) =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/reports/:projectId/:version/compare/price"
          element={<PriceComparePage />}
        />
      </Routes>
    </MemoryRouter>,
  );

const mkResp = (
  overrides: Partial<PriceCompareResponse> = {},
): PriceCompareResponse => ({
  bidders: [
    { bidder_id: 1, bidder_name: "甲公司" },
    { bidder_id: 2, bidder_name: "乙公司" },
  ],
  items: [
    {
      item_name: "水泥",
      unit: "吨",
      mean_unit_price: 100,
      has_anomaly: true,
      cells: [
        { bidder_id: 1, unit_price: 100, total_price: 1000, deviation_pct: 0 },
        { bidder_id: 2, unit_price: 100, total_price: 1000, deviation_pct: 0 },
      ],
    },
    {
      item_name: "钢筋",
      unit: "吨",
      mean_unit_price: 250,
      has_anomaly: false,
      cells: [
        {
          bidder_id: 1,
          unit_price: 200,
          total_price: 2000,
          deviation_pct: -20,
        },
        {
          bidder_id: 2,
          unit_price: 300,
          total_price: 3000,
          deviation_pct: 20,
        },
      ],
    },
  ],
  totals: [
    { bidder_id: 1, unit_price: null, total_price: 3000, deviation_pct: null },
    { bidder_id: 2, unit_price: null, total_price: 4000, deviation_pct: null },
  ],
  ...overrides,
});

describe("PriceComparePage", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("渲染表格 + 投标人列头 + 报价项", async () => {
    vi.spyOn(api, "getComparePrice").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/price");

    await waitFor(() => {
      expect(screen.getByText("甲公司")).toBeInTheDocument();
      expect(screen.getByText("乙公司")).toBeInTheDocument();
      expect(screen.getByText("水泥")).toBeInTheDocument();
      expect(screen.getByText("钢筋")).toBeInTheDocument();
    });
  });

  it("异常行有 bg-red-50", async () => {
    vi.spyOn(api, "getComparePrice").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/price");

    await waitFor(() => {
      const table = screen.getByTestId("price-table");
      const rows = table.querySelectorAll("tbody tr");
      // 水泥行(has_anomaly)
      expect(rows[0].className).toContain("bg-red-50");
      // 钢筋行(无 anomaly)
      expect(rows[1].className).not.toContain("bg-red-50");
    });
  });

  it("toggle 只看异常项", async () => {
    vi.spyOn(api, "getComparePrice").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/price");

    await waitFor(() => {
      expect(screen.getByText("钢筋")).toBeInTheDocument();
    });

    // 开启 toggle
    const toggle = screen.getByTestId("anomaly-toggle");
    fireEvent.click(toggle);

    // 钢筋应消失(非异常项)
    expect(screen.queryByText("钢筋")).not.toBeInTheDocument();
    // 水泥仍在
    expect(screen.getByText("水泥")).toBeInTheDocument();
  });

  it("列排序", async () => {
    vi.spyOn(api, "getComparePrice").mockResolvedValue(mkResp());
    renderAt("/reports/1/1/compare/price");

    await waitFor(() => {
      expect(screen.getByText("甲公司")).toBeInTheDocument();
    });

    // 点击甲公司列头排序
    fireEvent.click(screen.getByText("甲公司"));

    // 验证排序指示符出现
    expect(screen.getByText(/甲公司.*↑/)).toBeInTheDocument();
  });
});
