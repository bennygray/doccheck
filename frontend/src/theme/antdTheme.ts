/**
 * antd v5 ConfigProvider theme —— 从 tokens 派生
 */
import type { ThemeConfig } from "antd";
import { colors, radius, sizes, typography } from "./tokens";

export const antdTheme: ThemeConfig = {
  token: {
    colorPrimary: colors.primary,
    colorPrimaryHover: colors.primaryHover,
    colorPrimaryActive: colors.primaryActive,
    colorPrimaryBg: colors.primaryBg,

    colorText: colors.textPrimary,
    colorTextSecondary: colors.textSecondary,
    colorTextTertiary: colors.textTertiary,
    colorTextPlaceholder: colors.textPlaceholder,
    colorTextDisabled: colors.textDisabled,

    colorBorder: colors.border,
    colorBorderSecondary: colors.borderSecondary,
    colorSplit: colors.divider,

    colorBgBase: colors.bgBase,
    colorBgLayout: colors.bgLayout,
    colorBgContainer: colors.bgBase,
    colorBgElevated: colors.bgElevated,

    colorError: colors.danger,
    colorErrorBg: colors.dangerBg,
    colorSuccess: colors.success,
    colorSuccessBg: colors.successBg,
    colorWarning: colors.warning,
    colorWarningBg: colors.warningBg,

    fontFamily: typography.fontFamily,
    fontSize: typography.fontSizeBase,
    fontSizeSM: typography.fontSizeSm,
    fontSizeLG: typography.fontSizeLg,
    fontSizeHeading1: typography.fontSizeHeading1,
    fontSizeHeading2: typography.fontSizeHeading2,
    fontSizeHeading3: typography.fontSizeHeading3,
    lineHeight: typography.lineHeightBase,
    lineHeightHeading1: typography.lineHeightHeading,
    lineHeightHeading2: typography.lineHeightHeading,

    borderRadius: radius.base,
    borderRadiusLG: radius.lg,
    borderRadiusSM: radius.sm,

    controlHeight: sizes.controlHeight,
    controlHeightSM: sizes.controlHeightSm,
    controlHeightLG: sizes.controlHeightLg,

    // 企业克制阴影,盖住 antd 默认较重的阴影
    boxShadow: "0 1px 2px rgba(17, 24, 39, 0.04), 0 1px 3px rgba(17, 24, 39, 0.06)",
    boxShadowSecondary:
      "0 2px 4px rgba(17, 24, 39, 0.04), 0 4px 8px rgba(17, 24, 39, 0.06)",

    // 动画克制
    motionDurationMid: "0.2s",
    motionDurationSlow: "0.25s",

    wireframe: false,
  },
  components: {
    Button: {
      fontWeight: 500,
      primaryShadow: "none",
      defaultShadow: "none",
      dangerShadow: "none",
    },
    Card: {
      headerFontSize: 16,
      headerHeight: 48,
    },
    Table: {
      headerBg: "#fafbfc",
      headerColor: colors.textSecondary,
      headerSplitColor: colors.borderSecondary,
      rowHoverBg: "#f7f9fc",
    },
    Input: {
      activeShadow: "none",
      errorActiveShadow: "none",
    },
    Tag: {
      defaultBg: "#f5f7fa",
      defaultColor: colors.textSecondary,
    },
    Layout: {
      headerBg: colors.bgHeader,
      headerHeight: sizes.headerHeight,
      headerPadding: "0 24px",
      siderBg: colors.bgHeader,
      bodyBg: colors.bgLayout,
    },
  },
};
