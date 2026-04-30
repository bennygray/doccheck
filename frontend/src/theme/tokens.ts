/**
 * 设计 token —— 商务大气,不 AI 味
 *
 * 原则:
 * - 主色克制深蓝,避开紫渐变 / 霓虹 / 玻璃拟态
 * - 中性色偏冷,卡片纯白,底色冷灰
 * - 圆角 6px、阴影淡化,企业级克制
 * - 语气色(danger/success/warning)偏砖质而非霓虹
 *
 * 对应文档:docs/design-language.md
 */

export const colors = {
  // 主色:克制深蓝(非紫、非渐变)
  primary: "#1d4584",
  primaryHover: "#163868",
  primaryActive: "#122c54",
  primaryBg: "#eef3fb",

  // 中性
  textPrimary: "#1f2328",
  textSecondary: "#5c6370",
  textTertiary: "#8a919d",
  textPlaceholder: "#b1b6bf",
  textDisabled: "#c7ccd3",

  // 边框 & 分割
  border: "#e4e7ed",
  borderSecondary: "#ebedf0",
  divider: "#f0f2f5",

  // 背景
  bgBase: "#ffffff",
  bgLayout: "#f5f7fa",
  bgElevated: "#ffffff",
  bgHeader: "#ffffff",

  // 语气色 (砖质,非霓虹)
  danger: "#c53030",
  dangerBg: "#fdecec",
  success: "#2d7a4a",
  successBg: "#e8f3ec",
  warning: "#c27c0e",
  warningBg: "#fcf3e3",
  info: "#1d4584",
  infoBg: "#eef3fb",

  // 模板段灰底(detect-tender-baseline §7):baseline_matched 段落/单元格背景
  bgTemplate: "rgba(138, 145, 157, 0.08)",
} as const;

export const typography = {
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
  fontFamilyMono:
    '"SF Mono", Menlo, Consolas, "Courier New", "Microsoft YaHei", monospace',

  fontSizeBase: 14,
  fontSizeSm: 12,
  fontSizeLg: 16,
  fontSizeXl: 20,
  fontSizeHeading1: 28,
  fontSizeHeading2: 22,
  fontSizeHeading3: 18,

  lineHeightBase: 1.6,
  lineHeightHeading: 1.35,
} as const;

export const spacing = {
  xxs: 4,
  xs: 8,
  sm: 12,
  md: 16,
  lg: 24,
  xl: 32,
  xxl: 48,
} as const;

export const radius = {
  sm: 4,
  base: 6,
  lg: 8,
  xl: 12,
} as const;

export const shadows = {
  // 企业克制阴影,不用发光/渐变
  xs: "0 1px 2px rgba(17, 24, 39, 0.04)",
  sm: "0 1px 2px rgba(17, 24, 39, 0.04), 0 1px 3px rgba(17, 24, 39, 0.06)",
  md: "0 2px 4px rgba(17, 24, 39, 0.04), 0 4px 8px rgba(17, 24, 39, 0.06)",
  lg: "0 4px 8px rgba(17, 24, 39, 0.05), 0 12px 24px rgba(17, 24, 39, 0.08)",
} as const;

// 关键尺寸
export const sizes = {
  headerHeight: 56,
  sidebarWidth: 232,
  controlHeight: 36,
  controlHeightSm: 28,
  controlHeightLg: 44,
} as const;
