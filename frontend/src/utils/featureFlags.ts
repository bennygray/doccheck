/**
 * Vite build-time feature flags.
 *
 * detect-tender-baseline §7 D10:VITE_TENDER_BASELINE_ENABLED 默认 false,
 * 关闭时招标文件相关 UI 一律隐藏(项目页区块 / 报告 Badge / 模板段灰底 / 预检查 dialog 等)。
 */

function readFlag(value: unknown): boolean {
  if (typeof value !== "string") return false;
  return value.toLowerCase() === "true";
}

export function isTenderBaselineEnabled(): boolean {
  return readFlag(import.meta.env.VITE_TENDER_BASELINE_ENABLED);
}
