/**
 * L1 前端:api client — 2xx 返回 JSON / 非 2xx 抛错
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";

describe("api client", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("2xx 返回解析后的 JSON", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => ({ status: "ok", db: "ok" }),
    });

    const result = await api.health();
    expect(result).toEqual({ status: "ok", db: "ok" });
  });

  it("非 2xx 抛错", async () => {
    (fetch as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: false,
      status: 503,
      statusText: "Service Unavailable",
      json: async () => ({ status: "degraded" }),
    });

    await expect(api.health()).rejects.toThrow(/503/);
  });
});
