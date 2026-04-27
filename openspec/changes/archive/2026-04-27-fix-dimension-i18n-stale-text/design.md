# design: fix-dimension-i18n-stale-text

## D-1 修补范围(决策:严格最小)

**只补/改 6 个字面量,不抽工具,不动逻辑。**

| 文件 | 行 | 现状 | 修后 |
|---|---|---|---|
| DimensionDetailPage.tsx | ~65 (DIMENSION_LABELS 末尾) | 缺 2 项 | 加 `price_total_match: "投标总额完全相等"` + `price_overshoot: "超过最高限价"` |
| ComparePage.tsx | ~43 (DIMENSION_LABELS 末尾) | 缺 2 项 | 同上 |
| DetectProgressIndicator.tsx | ~44 (DIMENSION_LABELS 末尾) | 缺 2 项 | 同上 |
| DetectProgressIndicator.tsx | 163 | "11 个维度检测 agent" | "13 个维度检测 agent" |
| ReportPage.tsx | 545 | "11 个维度的得分雷达" | "13 个维度的得分雷达" |

**ReportPage.tsx DIMENSION_LABELS / DIMENSION_SHORT 已含 2 新维**(fix-bug-triple-and-direction-high 时加过),不再动。

## D-2 中文 label 措辞决策

延用 ReportPage.tsx 已有定义(单一真相源):
- `price_total_match` = "投标总额完全相等"(长名)
- `price_overshoot` = "超过最高限价"(长名)

短名(radar 轴)不需要,DimensionDetail / Compare / DetectProgress 都用长名。

## I-Frontend 实施

每个 map 在末尾追加 2 行:

```ts
const DIMENSION_LABELS: Record<string, string> = {
  // ...既有 11 项不动
  price_total_match: "投标总额完全相等",
  price_overshoot: "超过最高限价",
};
```

字面量数字直接 in-place 改 11→13。

## I-Test

- `[L1]` `cd frontend && npx tsc --noEmit`(类型不变,但确保编辑没引入 typo)
- `[L1]` `cd frontend && npm test`(Vitest 114 case;若有 case 断言 "11 个维度" 字面量则随改;预扫一遍)
- `[L3]` Claude_in_Chrome 走查:
  - 新建 walkthrough 项目(若需)→ 跑检测 → 验证检测进度面板"调度 13 个维度"
  - 报告页雷达描述"13 个维度"
  - 维度明细页 `price_overshoot` 行显示"超过最高限价"
  - 对比总览页若命中 `price_overshoot`/`price_total_match` 维度,显示中文
  - 截图归档到 `e2e/artifacts/fix-dimension-i18n-stale-text-<date>/`

## D-3 NOT 做

- 不抽 `dimensionLabels.ts` 共享 util(follow-up,memory 已登记)
- 不动后端 / spec / 权重
- 不修 `agent_tasks` 内的英文 key(那是 backend 真实标识,不能本地化)
- 不改 admin/rules 页 i18n(独立 scope,本次未触发)
