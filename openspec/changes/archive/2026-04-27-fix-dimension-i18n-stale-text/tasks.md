# Tasks

> 纯前端 UI copy / i18n 修补,无后端改动,无 spec delta。
> 验收顺序:impl(1-4) → 测试(5-6) → manual(7) → 全量绿(8)。

## 1. 维度明细页 i18n 补全

- [x] 1.1 [impl] `frontend/src/pages/reports/DimensionDetailPage.tsx` DIMENSION_LABELS 末尾追加 `price_total_match: "投标总额完全相等"` + `price_overshoot: "超过最高限价"` 2 行

## 2. 对比总览页 i18n 补全

- [x] 2.1 [impl] `frontend/src/pages/reports/ComparePage.tsx` DIMENSION_LABELS 末尾追加同 2 行

## 3. 检测进度面板 i18n + stale text

- [x] 3.1 [impl] `frontend/src/components/detect/DetectProgressIndicator.tsx` DIMENSION_LABELS 末尾追加同 2 行
- [x] 3.2 [impl] 同文件 line 163 "正在调度 11 个维度检测 agent" → "正在调度 13 个维度检测 agent"

## 4. 报告总览雷达描述 stale text

- [x] 4.1 [impl] `frontend/src/pages/reports/ReportPage.tsx` line 545 "11 个维度的得分雷达" → "13 个维度的得分雷达"

## 5. L1 测试

- [x] 5.1 [L1] `cd frontend && npx tsc --noEmit` ✅ 0 errors
- [x] 5.2 [L1] `cd frontend && npm test` ✅ 114 passed (25 files);预扫确认无 "11 个维度" 字面量断言

## 6. L2 测试

(本 change 零后端改动,L2 不需跑;若 archive 校验要求,可跑 `pytest backend/tests/e2e/` 走形式 — 此处明确 skip)

## 7. L3 manual 走查凭证(Claude_in_Chrome)

- [x] 7.1 [L3] 用既有或新建 walkthrough 项目,启动检测;**进度面板** 截图,确认"调度 13 个维度"文案
- [x] 7.2 [L3] 报告**总览页**截图,确认"13 个维度的得分雷达"
- [x] 7.3 [L3] **维度明细页**截图,确认 `price_overshoot` / `price_total_match` 行显示中文 label
- [x] 7.4 [L3] **对比总览页**截图(含 `price_overshoot` 命中行)中文 label
- [x] 7.5 [L3] 凭证归档 `e2e/artifacts/fix-dimension-i18n-stale-text-<YYYY-MM-DD>/`(README + 4 张截图)

## 8. 全量测试总汇

- [x] 8.1 跑 [L1][L2][L3] 全部测试,全绿(L2 跳过见 6;L1 + L3 全过即可)
