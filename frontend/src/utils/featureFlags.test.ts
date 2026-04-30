/**
 * L1: featureFlags.ts(detect-tender-baseline §7.17)
 *
 * 覆盖:VITE_TENDER_BASELINE_ENABLED 'true'/'false'/'TRUE'/missing/non-string 的解析口径。
 * 关键约束:flag=false 时 isTenderBaselineEnabled() 必须返 false(灰度兜底)。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("isTenderBaselineEnabled", () => {
  let originalEnv: ImportMetaEnv;

  beforeEach(() => {
    originalEnv = { ...import.meta.env };
  });

  afterEach(() => {
    vi.resetModules();
    Object.assign(import.meta.env, originalEnv);
  });

  async function loadFlag(value: unknown): Promise<boolean> {
    vi.resetModules();
    (import.meta.env as Record<string, unknown>).VITE_TENDER_BASELINE_ENABLED =
      value;
    const mod = await import("./featureFlags");
    return mod.isTenderBaselineEnabled();
  }

  it("flag='true' → true", async () => {
    expect(await loadFlag("true")).toBe(true);
  });

  it("flag='TRUE'(大小写不敏感) → true", async () => {
    expect(await loadFlag("TRUE")).toBe(true);
  });

  it("flag='false' → false", async () => {
    expect(await loadFlag("false")).toBe(false);
  });

  it("flag 未设置(undefined)→ false(灰度兜底)", async () => {
    expect(await loadFlag(undefined)).toBe(false);
  });

  it("flag 空字符串 → false", async () => {
    expect(await loadFlag("")).toBe(false);
  });

  it("flag 任意大小写'true' 字面量等价 → true", async () => {
    expect(await loadFlag("True")).toBe(true);
    expect(await loadFlag("tRuE")).toBe(true);
  });

  it("flag 任意非 'true' 字面量(0/no/random) → false", async () => {
    expect(await loadFlag("0")).toBe(false);
    expect(await loadFlag("no")).toBe(false);
    expect(await loadFlag("yes")).toBe(false);
    expect(await loadFlag("anything-else")).toBe(false);
  });
});
