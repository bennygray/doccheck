/**
 * 报告相关页面共用的顶部导航:面包屑 + 标题 + 子 Tab
 * 供 ReportPage / DimensionDetailPage / ComparePage 家族 / AuditLogPage 复用
 *
 * 视觉:克制的 breadcrumb + 大标题 + 主按钮区(可选 right actions)
 */
import { Link } from "react-router-dom";
import { Breadcrumb, Tabs, Typography } from "antd";
import type { ReactNode } from "react";

interface Props {
  projectId: string;
  version: string;
  title: string;
  subtitle?: string;
  /** 顶部 Tab 当前 key:null/undefined 时不显示 Tab */
  tabKey?: "report" | "dim" | "compare" | "logs" | null;
  /** 右上角操作按钮区 */
  extra?: ReactNode;
}

const TAB_ITEMS = [
  { key: "report", label: "总览" },
  { key: "dim", label: "维度明细" },
  { key: "compare", label: "对比" },
  { key: "logs", label: "日志" },
];

export function ReportNavBar({
  projectId,
  version,
  title,
  subtitle,
  tabKey,
  extra,
}: Props) {
  const basePath = `/reports/${projectId}/${version}`;
  const tabHref: Record<string, string> = {
    report: basePath,
    dim: `${basePath}/dim`,
    compare: `${basePath}/compare`,
    logs: `${basePath}/logs`,
  };

  return (
    <div>
      <Breadcrumb
        items={[
          { title: <Link to="/projects">项目</Link> },
          { title: <Link to={`/projects/${projectId}`}>项目详情</Link> },
          { title: `报告 v${version}` },
          ...(tabKey && tabKey !== "report"
            ? [{ title: TAB_ITEMS.find((t) => t.key === tabKey)?.label ?? "" }]
            : []),
        ]}
        style={{ marginBottom: 12 }}
      />
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-end",
          gap: 12,
          flexWrap: "wrap",
          marginBottom: 16,
        }}
      >
        <div>
          <Typography.Title
            level={3}
            style={{ margin: 0, fontWeight: 600, fontSize: 24 }}
          >
            {title}
          </Typography.Title>
          {subtitle ? (
            <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0", fontSize: 13 }}>
              {subtitle}
            </Typography.Paragraph>
          ) : null}
        </div>
        {extra}
      </div>
      {tabKey ? (
        <Tabs
          activeKey={tabKey}
          items={TAB_ITEMS.map((t) => ({
            key: t.key,
            label: <Link to={tabHref[t.key]}>{t.label}</Link>,
          }))}
          /* 去掉四角圆边框,改成一条底线 + 当前深蓝下划线;更克制,不 AI 味。 */
          tabBarStyle={{
            margin: 0,
            padding: "0 4px",
            borderBottom: "1px solid #e4e7ed",
          }}
        />
      ) : null}
    </div>
  );
}

export default ReportNavBar;
