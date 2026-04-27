# fix-dimension-i18n-stale-text — Manual 凭证

## 时间 + 关联
- 时间: 2026-04-27
- 上一 change: `fix-bug-triple-and-direction-high`(commit 47f731f)— 引入 2 新维度但 i18n map 4 处只改了 1 处
- 本 change scope: 补全其余 3 处 i18n map + 改 2 处 stale "11 个维度" 字面量(共 4 文件 6 改)

## 测试结果

| 层 | 套件 | 结果 |
|---|---|---|
| L1 backend | (零后端改动,跳过) | — |
| L1 frontend | `tsc --noEmit` | ✅ 0 errors |
| L1 frontend | `npm test`(Vitest) | ✅ 114 passed (25 files) |
| L2 | (零后端改动,跳过) | — |
| L3 manual | Claude_in_Chrome 走查 4 截图 | ✅ 全过 |

## L3 凭证(本目录)

### 数据集
- 项目 `i18n-fix-l3`(id=3026), max_price=**1,000,000**(故意低)
- 投标人: 供应商A(总额 1,368,000 → overshoot)+ 供应商C(总额 2,024,400 → overshoot)
- price_total_match **不触发**(2 家 totals 不同,符合预期)
- price_overshoot **触发铁证**(2 家都超限)

### 4 张截图

| 截图 | 验证点 | 关键观察 |
|---|---|---|
| [01-detect-progress-13-agents.png](01-detect-progress-13-agents.png) | 检测进度面板 13 agent 网格 | **网格中 "超过最高限价" / "投标总额完全相等" 中文 label 已显示**(原本是英文 key) |
| [02-report-radar-13.png](02-report-radar-13.png) | 报告总览雷达图说明 | **"13 个维度的得分雷达;..."**(原本是 "11 个维度") + 雷达图 13 轴(超限/总额相等含) |
| [03-dim-overshoot-chinese.png](03-dim-overshoot-chinese.png) | 维度明细 price_overshoot 行 | **铁证区第 2 行显示"超过最高限价"中文 label**(原本是英文 `price_overshoot` 重复显示) |
| [04-compare-overview.png](04-compare-overview.png) | 对比总览页 pair-level 维度中文 | UTF-8 干净,pair 级维度(结构/作者/文本)均中文。注:price_overshoot 是 global 不显示在 pair view(架构合理) |

### 证据完整性
- 截图工具: Playwright headless chromium(`capture.py`)
- 跑流程: login → create proj → upload 2 zip → wait priced → start detect → wait completed → 4 screenshots
- 截图脚本可重跑: `uv run --with playwright --with requests python capture.py`

## ⚠️ 已知 follow-up(本次 NOT 修)

1. **抽 `frontend/src/utils/dimensionLabels.ts` 共享 util**:本次仍维持 4 处独立 map,future 加新维度仍要改 4 次。已登记到 `docs/handoff.md`。
2. **AI 综合研判文案中出现英文 key**(如 `price_overshoot`):这是 LLM 生成的自然语言文本,不在 UI label map 控制范围;需另外改 prompt template / OutputAnalysis 或后处理。本次 NOT 改。

## 凭证文件
- README.md(本文件)
- capture.py(截图脚本)
- 01-detect-progress-13-agents.png
- 02-report-radar-13.png
- 03-dim-overshoot-chinese.png
- 04-compare-overview.png
- _state.json(项目 id 留 cleanup)

## 相关
- proposal: `openspec/changes/fix-dimension-i18n-stale-text/proposal.md`
- design: `openspec/changes/fix-dimension-i18n-stale-text/design.md`
- tasks: `openspec/changes/fix-dimension-i18n-stale-text/tasks.md`(8 章全 [x])
