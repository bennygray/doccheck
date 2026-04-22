/**
 * C16 对比子页签:总览 / 报价 / 元数据 / 文本
 * 供 ComparePage / PriceComparePage / MetaComparePage / TextComparePage 共享
 */
import { Link } from "react-router-dom";
import { Tabs } from "antd";

interface Props {
  projectId: string;
  version: string;
  activeKey: "overview" | "price" | "metadata" | "text";
  extra?: React.ReactNode;
}

export function CompareSubTabs({ projectId, version, activeKey, extra }: Props) {
  const base = `/reports/${projectId}/${version}/compare`;
  const items = [
    { key: "overview", label: <Link to={base}>对比总览</Link> },
    { key: "price", label: <Link to={`${base}/price`}>报价对比</Link> },
    { key: "metadata", label: <Link to={`${base}/metadata`}>元数据对比</Link> },
    { key: "text", label: <Link to={`${base}/text`}>文本对比</Link> },
  ];

  return (
    <Tabs
      activeKey={activeKey}
      items={items}
      tabBarExtraContent={extra}
      /* 子 Tab 比主 Tab 更克制:size small + 背景融合父卡 */
      size="small"
      tabBarStyle={{
        margin: 0,
        padding: "4px 16px 0",
        background: "#fafbfc",
        borderBottom: "1px solid #e4e7ed",
      }}
    />
  );
}

export default CompareSubTabs;
