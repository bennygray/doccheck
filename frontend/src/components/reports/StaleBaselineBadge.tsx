/**
 * 老版本无 tender 警示 Badge(detect-tender-baseline §7.7)。
 *
 * 报告级 baseline_source 缺失或为 'none' 但项目当前有招标文件 → 提示老版本未享受新基线,
 * 引导用户重新检测。在 ReportPage 头部展示。
 */
import { Tag, Tooltip } from "antd";
import { ExclamationCircleOutlined } from "@ant-design/icons";

interface Props {
  size?: "small" | "default";
}

export default function StaleBaselineBadge({ size = "default" }: Props) {
  return (
    <Tooltip title="此报告生成时项目尚未上传招标文件,基线为 L2/L3。建议补充招标文件后重新检测,获取 L1 基线下的精确判定。">
      <Tag
        data-testid="stale-baseline-badge"
        icon={<ExclamationCircleOutlined />}
        color="warning"
        style={{
          margin: 0,
          fontSize: size === "small" ? 11 : 12,
          padding: size === "small" ? "0 6px" : undefined,
        }}
      >
        老版本无基线
      </Tag>
    </Tooltip>
  );
}
