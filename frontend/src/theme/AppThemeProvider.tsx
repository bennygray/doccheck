/**
 * antd 全局 ConfigProvider 包裹 —— 主题 + 中文 locale + React 19 兼容 patch
 */
import "@ant-design/v5-patch-for-react-19";
import { ConfigProvider, App as AntdApp } from "antd";
import zhCN from "antd/locale/zh_CN";
import type { ReactNode } from "react";
import { antdTheme } from "./antdTheme";

export function AppThemeProvider({ children }: { children: ReactNode }) {
  return (
    <ConfigProvider theme={antdTheme} locale={zhCN}>
      <AntdApp>{children}</AntdApp>
    </ConfigProvider>
  );
}
