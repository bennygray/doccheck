# proposal: fix-dimension-i18n-stale-text

## Why

`fix-bug-triple-and-direction-high`(commit 47f731f)新增 2 个维度(`price_overshoot` / `price_total_match`)和 13 维聚合,但前端有 4 处 `DIMENSION_LABELS` map 同源副本,只改了 1 处(ReportPage.tsx 13 项 + radar short 13 项),漏改其余 3 处:

- `frontend/src/pages/reports/DimensionDetailPage.tsx` 仍 11 项
- `frontend/src/pages/reports/ComparePage.tsx` 仍 11 项
- `frontend/src/components/detect/DetectProgressIndicator.tsx` 仍 11 项

加上 2 处 stale 字面量描述也忘改:
- `ReportPage.tsx:545` "11 个维度的得分雷达"(应是 13)
- `DetectProgressIndicator.tsx:163` "正在调度 11 个维度检测 agent"(应是 13)

后果:维度明细页 / 对比总览页 / 检测进度面板上,新 2 维显示英文 key(`price_overshoot` / `price_total_match`)而非中文 label;报告/进度面板有 stale 文案描述。**不影响检测正确性 / 铁证识别 / 评分 / 证据链**(2026-04-27 main walkthrough 已验证),仅影响中文展示一致性。

## What Changes

**纯 UI copy / i18n 修复,4 文件 + 6 个字面量:**

1. `DimensionDetailPage.tsx` DIMENSION_LABELS 加 2 行
2. `ComparePage.tsx` DIMENSION_LABELS 加 2 行
3. `DetectProgressIndicator.tsx`:DIMENSION_LABELS 加 2 行 + L163 "11 个维度" → "13 个维度"
4. `ReportPage.tsx` L545 "11 个维度" → "13 个维度"

**不改契约 / 不改后端 / 不动权重 / 不动 spec**。无 spec delta。

## 例外说明(对齐 CLAUDE.md "孤立改文档/配置 change 例外")

本 change 是**纯前端 i18n / copy 修补**,无 spec 变化(spec 是后端契约层概念,UI 文案不涉及)。tasks.md 含:
- [impl] × 4 文件改动
- [L1] frontend tsc + Vitest(确认无 stale label 字符串断言被破坏)
- [L3] Claude_in_Chrome 走查 3 个页面(维度明细 / 对比总览 / 检测进度面板)截图凭证

不写 [L2] 是因为后端零改动;不写 [manual] 是因为 [L3] 已覆盖。

## Follow-up(本次 NOT 做)

将 4 处同源 `DIMENSION_LABELS` 抽到共享 `frontend/src/utils/dimensionLabels.ts` 工具,消除重复。**理由:本次 scope 严格限"最简修缺",抽工具属 refactor 风险;独立 change 处理。** 已在 docs/handoff.md 登记。
