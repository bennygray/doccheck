# L3 完整集 — detect-tender-baseline §8

- **Change**: `detect-tender-baseline` (M5)
- **Scope**: §7 前端基线 UI 全套 + §8.0 backend compare/report 透传 baseline_source/baseline_matched
- **Commit hash 验证版本**:
  - §7 前端: `e75e227`(已落)
  - §8.0 后端 patch + 本目录归档:本次 commit
- **测试日期**: 2026-04-30
- **测试性质**: 真后端 / 真 LLM(火山引擎 Ark) / 合成 L1 投标方 zip + 真模板 zip
- **运行人**: Claude Code (session, autonomous)
- **凭证目录**: `e2e/artifacts/detect-tender-baseline-2026-04-30/l3-full-demo/`

## TL;DR

§7 前端基线 UI + §8.0 后端 baseline 数据透传**功能正确**:招标文件上传卡 / 启动检测预检查 dialog / 报告页 baseline Badge / DimensionRow 招标基线 Tag / 双栏对比段灰底 / 重跑 dialog **5 张截图全部覆盖**,UI 与 Spec design 一致。

| 截图编号 | 流程 | 文件 | 状态 |
|---|---|---|---|
| ① | 招标文件上传卡 | `screenshots/1-tender-upload-card.png` | ✓ |
| ② | 启动检测预检查 dialog L2(3 投标方无 tender) | `screenshots/2-precheck-dialog-l2.png` | ✓ |
| ②b(bonus) | 启动检测预检查 dialog L3(2 投标方无 tender) | `screenshots/2b-precheck-dialog-l3.png` | ✓ |
| ③ | 报告页 L1 招标基线 Badge | `screenshots/3-report-l1-badge-viewport.png` | ✓ |
| ③b | DimensionRow 招标基线 Tag(text_similarity / price_consistency) | `screenshots/3b-report-dimension-baseline-tag.png` | ✓ |
| ④ | 双栏对比 L1 招标 段级 Tag + 灰底 | `screenshots/4-text-compare-baseline-gray.png` | ✓ |
| ⑤ | 重跑 dialog(已完成版本 + 上传新 tender) | `screenshots/5-rerun-after-tender-dialog.png` | ✓ |

## §8.0 backend patch(本次 commit 包含)

L3 demo 期间发现两处 backend 数据透传缺口,已在本 commit 一并修复:

1. **`backend/app/schemas/compare.py` + `routes/compare.py`**: 把 `PC.evidence_json.samples[i].baseline_matched/baseline_source` 透传到 `TextMatch`(否则前端"双栏对比模板段灰底"无法读到段级 baseline 标记)
2. **`backend/app/schemas/report.py` + `routes/reports.py`**: 在 `ReportResponse` + `ReportDimension` 加 `baseline_source` + `warnings` 字段;route 内**从 PC.evidence_json 聚合**:维度级 = 该维度所有 PC 最强 source(tender > consensus > metadata_cluster > none),报告级 = 所有维度最强 source(否则前端 ReportPage Badge 永远显示 L3)

### 回归证明
- backend e2e 全 **323 passed**(原 322,+1 因 §8.0 schema 改动而新增字段在已有 e2e 不破坏)
- backend unit 全 **1370 passed**
- frontend vitest 全 **145 passed**(2 个 StartDetectButton 老测试因 flag=true 加 precheck dialog 链路要更新 mock,已修)

## 1. 测试场景与数据

### L1 demo 项目(主轴)
- **id**: 4194
- **name**: `L1-synthetic-tender-baseline-demo`
- **owner**: admin (id 4968)
- **bid_code**: DEMO-L1
- **创建时间**: 2026-04-30T11:56:28Z

### Tender(招标方下发模板)
- **file_name**: `tmp_tender_template.zip`(139 KB)
- **md5**: `2f55b006bbcf831bc864feb50fc6090b`
- **parse_status**: extracted
- **segment_hashes**: 210
- **boq_baseline_hashes**: 10
- **来源**: `D:/documentcheck/tmp_tender_template.zip`(包含 4 份 docx/xlsx 模板)

### 投标方(合成 L1 demo:vendor 内容来自 tender,期望段 hash 命中率高)
| bidder_id | name | source archive | parse_status | segments_with_hash | overlap_with_tender | overlap_pct |
|---|---|---|---|---|---|---|
| 4777 | vendor-D | `tmp_synthetic_l1_zips/vendor-D.zip`(142 KB) | identified/priced | 190 | 187 | **98.4%** |
| 4778 | vendor-E | `tmp_synthetic_l1_zips/vendor-E.zip`(142 KB) | identified/priced | 190 | 187 | **98.4%** |
| 4779 | vendor-F | `tmp_synthetic_l1_zips/vendor-F.zip`(142 KB) | identified/priced | 190 | 187 | **98.4%** |

构造方式见 `D:/documentcheck/tmp_make_synth_zips.py`:vendor zip = tender 内 4 份 docx 加 `vendor-{X}-` 前缀(arcname 不同 → zip 整体 md5 不同;docx 文件内容字节完全相同 → 段级 hash 必命中 tender)。

### L2/L3 辅助项目(precheck dialog 截图用)
| project_id | 名称 | bidders | tender | 截图 |
|---|---|---|---|---|
| 4195 | L2-no-tender-3bidders-demo | 3 stub(extracted) | 无 | ② L2 |
| 4196 | L3-no-tender-2bidders-demo | 2 stub(extracted) | 无 | ②b L3 |

stub bidders 通过 DB 直插绕过解析 LLM 成本(precheck dialog 只判 `bidders.length` + terminal 状态,不需要真实文档)。

## 2. 检测过程

### 2.1 真 LLM v=1 run(基线版本)
- 启动:2026-04-30T12:00:25Z
- 完成:~12:00:30Z(约 5 秒)
- **27 任务,19 succeeded + 8 skipped,0 failed/0 timeout**
- text_similarity / section_similarity 全 **skipped**:`文档过短无法对比`(template docx 单 role body chars < 300,默认阈值)

### 2.2 真 LLM v=2 run(主 demo,降低 text_sim 阈值)
- backend 重启加 env:`TEXT_SIM_MIN_DOC_CHARS=50 SECTION_SIM_MIN_DOC_CHARS=50`
- 启动:2026-04-30T12:05:54Z
- 完成:~12:06:44Z(约 50 秒)
- **27 任务,25 succeeded + 2 skipped**
- 维度结果(节选):
  - text_similarity: **score=100.0 ironclad=True baseline_source=metadata_cluster**(LLM 判 plagiarism;baseline-bypass 仅对 exact_match label 生效,见 §3 design D8 + aggregator)
  - section_similarity / structure_similarity: 100.0 / ironclad=True
  - metadata_author / metadata_time: 100.0 / ironclad=True / metadata_cluster
  - **price_consistency: score=0.0 ironclad=False baseline_source=tender** ✓
  - **price_anomaly: score=0.0 ironclad=False baseline_source=tender** ✓
  - 总分 **98.0** 高风险 5 条铁证

### 2.3 PC 级 baseline 命中(v=2)
- 21 PCs total,**3 有 baseline_source='tender'**(都属 price_consistency 维度)、18 'none'
- 报告级聚合 baseline_source = **tender**(取所有维度最强)→ 前端 Badge 显示 **L1 招标基线**

### 2.4 LLM 实测成本
- v=1 run:基本免费(text_sim 全 skip,只跑了元数据/结构等本地算法 + 少量 LLM judge)
- v=2 run:实测约 ¥1 以内(LLM judge 集中在 text_sim 3 PC × 数 sample,exact_match 路径短路)
- **总计远低于预估 ¥3-5**(因合成 zip 文件高度重复 → exact_match label 占多数 → 不送 LLM)

## 3. UI 演示数据注入(§8 文本对比段灰底专用)

### 背景
真 LLM 在 v=2 把 vendor 间高相似 paragraphs 都判为 LLM `plagiarism` label(非 `exact_match`),而 §3 design D8 决定 baseline 旁路**只对 ≥50 字 exact_match** 生效(plagiarism 段被认定为"AI 判定的真抄袭",不能因 baseline 命中而豁免)。这意味着真 LLM 路径下,即使 vendor 文档段 100% 命中 tender hash,仍然 ironclad=True 且 baseline_source='none'(段级 baseline_matched=False)。

设计上正确(防 LLM 误判抄袭被 baseline 误豁免),但 **§8 截图 ④ 双栏对比段灰底** 无法直接演示。

### 注入方案
脚本 `D:/documentcheck/tmp_inject_baseline_for_ui_demo.py`:
- 把 PC 512(text_similarity, 4777-4778, v=2)的 evidence_json.samples 前 2 个 sample 的 `baseline_matched=true` + `baseline_source='tender'` 直接 SQL 写入
- PC 顶级 evidence_json.baseline_source='tender'

### 立场
- **本注入仅为 §7 前端 UI 渲染演示**,功能正确性由 backend §3 e2e `test_text_sim_baseline_e2e.py` 5 case 全覆盖(L1 tender 命中段 → ironclad-bypass / 段级 / 顶级字段写入)
- README 明确标注此为"UI 演示数据注入,非真 LLM 判定结果"
- 真客户场景下,baseline_matched=true 通常出现在:① tender 上传后 ② 投标方原文复用 tender 模板段(≥50 字 exact_match 路径)— 真实测试由 L1 unit + e2e 30 case 覆盖

## 4. 5 张截图详情

### ① 招标文件上传卡
**文件**: `screenshots/1-tender-upload-card.png` 92.9 KB

**期望**:
- 项目页含「招标文件」区块(feature flag VITE_TENDER_BASELINE_ENABLED=true)
- 区块标题「招标文件 · 共 1 份 · 用于建立模板基线(L1)」
- 拖拽上传 zone「点击或拖拽文件到此处上传招标文件 / .docx / .xlsx / .zip / .7z / .rar,最大 500MB」
- 已上传 tender 行 + 「已解析」绿 Tag

**实际**: 全部符合 ✓

### ② 启动检测预检查 dialog(L2)
**文件**: `screenshots/2-precheck-dialog-l2.png` 76.5 KB

**项目**: 4195(L2-no-tender-3bidders-demo,3 stub bidders 无 tender)

**期望**:
- 点击「启动检测」弹出 dialog 标题「启动检测前确认」
- 警告 Alert:「未上传招标文件 / 将自动启用 L2 共识基线(≥3 投标方时跨方共识识别模板段),精度略低于 L1。建议补充上传招标文件后重跑,可获得更精确的判定。」
- 「本项目不再提醒」checkbox + 「取消」 / 「确认启动」按钮

**实际**: 全部符合 ✓

### ②b 启动检测预检查 dialog(L3 — bonus)
**文件**: `screenshots/2b-precheck-dialog-l3.png` 73.4 KB

**项目**: 4196(L3-no-tender-2bidders-demo,2 stub bidders)

**期望**:
- 警告 Alert:「未上传招标文件 / 仅 2 家投标方,共识基线不可用,基线判定将降级到 L3(无基线),误报率可能升高。」

**实际**: 全部符合 ✓

### ③ 报告页 L1 招标基线 Badge
**文件**: `screenshots/3-report-l1-badge-viewport.png` 96.5 KB

**项目**: 4194(L1) v=2

**期望**:
- 报告头部:「检测报告 v2 / 生成于 2026/4/30 20:06:41」+ 右上角 **L1 招标基线** 蓝 Badge + 「导出 Word」按钮
- Hero 区:综合得分 98.0(高风险) + 维度雷达图

**实际**: Badge 显示 **L1 招标基线**(蓝)+ Hero 综合 98.0 + 雷达图 ✓

### ③b DimensionRow 招标基线 Tag
**文件**: `screenshots/3b-report-dimension-baseline-tag.png` 94.5 KB

**期望**:
- 文本相似度行:「铁证」红 Tag + **「招标基线」蓝 Tag** + 进度条 100.0
- 报价一致性行:「**招标基线**」蓝 Tag + 进度条 0.0(分值因 baseline 命中归零,前端 Tag 仍展示 source)

**实际**: 全部符合 ✓(老 baseline_source='metadata_cluster' 维度未单独显示 Tag,只在维度级 baseline_source != 'none' 时展示;UI 实现按 spec)

### ④ 双栏对比 L1 招标段级 Tag + 灰底
**文件**: `screenshots/4-text-compare-baseline-gray.png` 68.1 KB

**项目**: 4194 v=2 / pair=4777-4778 / text_similarity

**期望**:
- 左右栏每一段命中 baseline 时:「L1 招标」前缀小 Tag(蓝) + 灰底(rgba(138,145,157,0.08))
- 非 baseline 命中段:琥珀色 simBgColor(原 v=2 sim 高亮)

**实际**: 顶部 9 段 paragraphs 显示「L1 招标」前缀 Tag + 灰底,底部 5 段琥珀色 sim 高亮(自拟 / 品牌偏离表 等非 baseline)。**注入数据演示**(见 §3 注入方案);真实功能由 L1 e2e 覆盖。

### ⑤ 重跑 dialog
**文件**: `screenshots/5-rerun-after-tender-dialog.png` 78.5 KB

**项目**: 4194(已完成 v=2),先 API DELETE 旧 tender → playwright UI 上传新 tender(`tmp_tender_template_v2.zip`,md5 不同避开重复校验)

**期望**:
- 上传新 tender 后弹出 dialog 标题「新基线已就绪」
- info Alert:「招标文件已上传并解析 / 是否立即基于新基线重新检测?旧报告将保留,新版本与之并列展示。」
- 「稍后」/「立即重新检测」按钮

**实际**: 全部符合 ✓ + tender 列表显示「tmp_tender_template_v2.zip / 解析中」状态

## 5. JSON 凭证

| 文件 | 说明 |
|---|---|
| `project_state_pre_analysis.json` | 项目 4194 + tender + bidders 解析后状态(分析前快照) |
| `analysis_status_final.json` | v=1 run agent_tasks 终态(19 succeeded + 8 skipped) |
| `analysis_status_v2_final.json` | v=2 run agent_tasks 终态(25 succeeded + 2 skipped) |
| `report_v1.json` / `report_v2.json` | `/reports/{v}` 完整响应(含报告级 baseline_source) |
| `dimensions_v1.json` / `dimensions_v2.json` | `/reports/{v}/dimensions` 13 维度详情 |
| `pairs_v1.json` / `pairs_v2.json` | `/reports/{v}/pairs` PC 列表 |

## 6. 已知 caveat

1. **真 LLM exact_match label 命中率取决于 LLM**:本 demo 的 v=2 用真 LLM 后 text_sim 全 plagiarism label,导致段级 baseline_matched=false。Backend §3 design D8 设计如此(plagiarism 不做 baseline 旁路)。截图 ④ 双栏段灰底由 evidence_json 直接注入演示
2. **报告级 baseline_source 聚合策略**:取所有维度最强 source(tender > consensus > metadata_cluster > none)。L1 demo 中即使 text_sim baseline_source='metadata_cluster',只要任一维度有 'tender',报告级就 = 'tender' → 前端 Badge L1 蓝。这是 design 意图(L1 即使不主导,仍是最高优先级标识)
3. **TenderDocument soft-delete 后 md5 dedup 不重置**:重跑 dialog 用 v2 zip(不同 md5)绕过。这是另一个 known bug,不在本 change scope
4. **L1 demo 投标方文档 100% 重复**:导致 metadata_cluster / structure_similarity / metadata_author / metadata_time 都 100 ironclad(模板内 placeholder 字段全空,vendor 间一致),非 baseline-bypass 范畴

## 7. 配套测试覆盖

- backend e2e 5 baseline 测试套件 **25 passed**(test_compare_api / test_text_sim_baseline_e2e / test_section_sim_baseline_e2e / test_judge_baseline_injection_e2e / test_price_consistency_boq_e2e / test_price_anomaly_baseline_e2e)
- backend unit 1370 passed,backend e2e 全 323 passed
- frontend vitest 145 passed,build 0 tsc errors

## 8. 复现命令

```bash
# 后端启动(env 降低 text_sim 阈值方便本 demo)
cd backend
TEXT_SIM_MIN_DOC_CHARS=50 SECTION_SIM_MIN_DOC_CHARS=50 \
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8001

# 前端启动(flag=true)
cd frontend
echo "VITE_TENDER_BASELINE_ENABLED=true" > .env
npm run dev -- --port 5180

# 合成 vendor zips
uv run python tmp_make_synth_zips.py

# 创建项目 + 上传 tender + 3 bidders
uv run python tmp_setup_l1_project.py

# 触发分析(等终态)
uv run python tmp_trigger_v2.py

# 注入 UI demo 数据
uv run python tmp_inject_baseline_for_ui_demo.py

# 截图(playwright headless)
uv run python tmp_capture_screenshots.py
uv run python tmp_capture_screenshot_3_viewport.py
uv run python tmp_capture_screenshot_5.py
```
