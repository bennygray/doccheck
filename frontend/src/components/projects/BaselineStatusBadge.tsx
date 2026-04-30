/**
 * 基线状态 Badge(detect-tender-baseline §7.4 / D11)。
 *
 * 优先级:tender → L1(品牌蓝) > consensus → L2(琥珀) > metadata_cluster / none → L3(中性灰)。
 * Tooltip 解释每个等级 + ≤2 投标方时的 baseline_unavailable 警示。
 */
import { Tag, Tooltip } from "antd";
import { colors } from "../../theme/tokens";
import type { BaselineSource, BaselineStatus } from "../../types";

export function baselineSourceToStatus(
  source: BaselineSource | null | undefined,
): BaselineStatus {
  if (source === "tender") return "L1";
  if (source === "consensus") return "L2";
  return "L3";
}

const STATUS_META: Record<
  BaselineStatus,
  { label: string; color: string; bg: string; tooltip: string }
> = {
  L1: {
    label: "L1 招标基线",
    color: colors.primary,
    bg: colors.primaryBg,
    tooltip: "已上传招标文件,模板段命中招标 hash → 自动剔除铁证,降低误报",
  },
  L2: {
    label: "L2 共识基线",
    color: colors.warning,
    bg: colors.warningBg,
    tooltip: "未上传招标文件,但 ≥3 投标方共识识别出模板段 → 准基线,精度略低于 L1",
  },
  L3: {
    label: "L3 无基线",
    color: colors.textTertiary,
    bg: "#f5f7fa",
    tooltip: "≤2 投标方且未上传招标文件,基线判定降级,铁证按原规则触发",
  },
};

interface Props {
  source: BaselineSource | null | undefined;
  warnings?: string[];
  size?: "small" | "default";
}

export default function BaselineStatusBadge({
  source,
  warnings,
  size = "default",
}: Props) {
  const status = baselineSourceToStatus(source);
  const meta = STATUS_META[status];
  const hasLowBidderWarning = (warnings ?? []).includes(
    "baseline_unavailable_low_bidder_count",
  );
  const tooltipBody = hasLowBidderWarning
    ? `${meta.tooltip}(投标方不足 3 家,共识基线不可用)`
    : meta.tooltip;

  return (
    <Tooltip title={tooltipBody}>
      <Tag
        data-testid="baseline-status-badge"
        data-baseline-status={status}
        style={{
          margin: 0,
          color: meta.color,
          background: meta.bg,
          borderColor: meta.color,
          fontWeight: 500,
          fontSize: size === "small" ? 11 : 12,
          padding: size === "small" ? "0 6px" : undefined,
        }}
      >
        {meta.label}
      </Tag>
    </Tooltip>
  );
}
