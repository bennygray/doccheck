# main 分支 e2e 全量走查 — 2026-04-27

## 时间 + 范围
- 时间: 2026-04-27
- 仓库: main 分支(commit `ea28a43`)
- 范围: A 阶段 L1+L2 自动套件全跑 + B 阶段 Claude_in_Chrome 驱动 UI walkthrough(超出单 change 范围,广度覆盖核心用户路径)

## A 阶段 — 自动套件结果

| 套件 | 命令 | 结果 | 时长 |
|---|---|---|---|
| L1 backend pytest unit | `pytest backend/tests/unit/` | **1182 passed / 8 skipped** ✅ | 40s |
| L1 frontend tsc | `cd frontend && npx tsc --noEmit` | **0 errors** ✅ | <30s |
| L1 frontend Vitest | `cd frontend && npm test` | **114 passed (25 files)** ✅ | 47s |
| L2 backend e2e pytest | `TEST_DATABASE_URL=... pytest backend/tests/e2e/` | **286 passed / 2 skipped** ✅ | 2:33 |

L2 用 `docker compose -f docker-compose.test.yml up -d`(端口 55432)隔离 dev DB。

## B 阶段 — Claude_in_Chrome UI walkthrough

### 数据集
- 项目: `main-walkthrough`(id=3025), max_price=2,000,000
- 投标人:**3 个真实供应商 zip**(`供应商A.zip` 42.7MB / `供应商B.zip` 58.7MB / `供应商C.zip` 34.0MB)
- 来源:`C:/Users/7way/xwechat_files/bennygray_019b/msg/file/2026-04/投标文件模板2/投标文件模板2/`
- 上传方式:**Python `requests` multipart**(显式 UTF-8,避免 Windows curl GBK shell 乱码;前一次 fix-bug 走查的乱码已根因定位)

### 关键输入 / 输出对照

| 步骤 | 输入 | 输出 | 截图 |
|---|---|---|---|
| **B1 上传** | 3 zip 文件 + name=`供应商A/B/C` | 3 bidder 创建 201,parse_status=pending | (B2 接续) |
| **B2 解析+输入验证** | 自动 extract→identify→price 流水 | 全部 priced;**totals**:供A=1,368,000 / 供B=1,458,000 / 供C=2,024,400;identity sufficient×3 | `01-project-detail-completed.png` |
| **B3 启动检测** | 点 UI"启动检测" | v=1 启动;27 个 task = pair 7×3 + global 6;Tag "待检测"→"检测中"→"已完成"**未切页同步**(Bug 1 二次实战确认) | `01-project-detail-completed.png` |
| **B4 报告总览** | 点"查看报告" | **总分 92.0/100,高风险,3 条铁证**;13 维雷达图;AI 综合研判提到 3385×3386 文本 83.82% + 章节 56.6% 突破铁证阈值,加权初判 85.0 上调 92.0 | `02-report-overview.png` |
| **B5 维度明细** | 点"维度明细" | **6 维命中(4 铁证·1 高风险·1 中风险)**:结构 100.0铁证 / `price_overshoot` 100.0铁证(供C ratio=0.0122 超限符合预期)/ 文本 83.8铁证 / 章节 56.6铁证 / 风格 100.0 高风险 / 元数据·作者 62.5 中风险;`price_total_match` **未触发**(3 家 totals 不同符合预期) | `03-dimensions-detail.png` |
| **B6 查看证据** | 点"查看证据"链接 | 跳转到对比页;3 对投标人都命中 | `04-compare-overview.png` |
| **B7-1 报价对比** | 点"报价对比"子 tab | 7 项 × 3 投标人 + 均价矩阵;总报价 1,368,000 / 1,458,000 / 2,024,400 与 API 一致 | `05-compare-price.png` |
| **B7-2 元数据对比** | 点"元数据对比"子 tab | **铁证级元数据同源:** 供A 和供C 作者都=`LP`,创建时间完全相同 `2023/10/09 15:16`,文档模板都=`Normal.dotm`,创建软件 GUID 同一份 `F1E327BC-269C-435d-A152-05C5408002CA` | `06-compare-metadata.png` |
| **B7-3 文本对比** | 点"文本对比"子 tab + 选 #3385×#3386 | **段落级双栏对比** 90%+ 相似;模板段落几乎一样,只投标人名+日期不同(经典围标特征) | `07-compare-text-3385-3386.png` |
| **B8 导出 Word** | 点"导出 Word",轮询 job_id | POST /export → 202 + job_id=38;GET /exports/38/download → 200 + **38,556 bytes** docx;**69 段落,含标题/项目元数据/AI 研判/13 维详情** | `exported.docx`(实际可下载文件) |

### 数据真实性
- LLM 是真调用(非 mock);见 `agent_tasks.json` 中各 LLM agent 的 elapsed_ms(text_similarity 单次 ~30s)
- 报告完整快照见 `report.json`(total_score=92.0, risk_level=high, 13 维 dimensions 数组)

## 已知非 blocker 缺口(超出本次 walkthrough scope)
1. **`price_overshoot` / `price_total_match` 中文 label i18n 缺失**:报告维度明细页该两行的中文 label 显示为英文 key,而非 design 预期的"超过最高限价"/"投标总额完全相等"。不影响检测正确性 + 铁证识别 + 数值 + 证据链;仅维度名称展示。已在 `fix-bug-triple-and-direction-high` 凭证里登记,待 follow-up change。
2. **报告"基于 13 维度加权合成"vs 雷达图描述"11 个维度的得分雷达"文案不一致**(11 是旧值 stale text):新 change 跨过了 11→13 但 chart 文字描述未刷。也是 follow-up i18n/copy 修整范畴。
3. **供B"建设工程委托监理"unit_price = null** 但 total_price=486000 — 来源数据缺单价,UI 用横线兜底,正确。

## 凭证文件
- [README.md](README.md)(本文件)
- [01-project-detail-completed.png](01-project-detail-completed.png) — 项目详情页 Tag "已完成"(Bug 1 fix 二次实战)
- [02-report-overview.png](02-report-overview.png) — 报告总览(综合得分 92.0 / 雷达 / AI 研判)
- [03-dimensions-detail.png](03-dimensions-detail.png) — 维度明细 6 维命中分级展示
- [04-compare-overview.png](04-compare-overview.png) — 对比总览 3 对投标人 4 维度命中
- [05-compare-price.png](05-compare-price.png) — 报价对比矩阵
- [06-compare-metadata.png](06-compare-metadata.png) — 元数据对比矩阵(同源指纹证据)
- [07-compare-text-3385-3386.png](07-compare-text-3385-3386.png) — 文本对比双栏(供B vs 供C 段落级证据)
- [exported.docx](exported.docx) — 实际导出的 Word 报告(38,556 bytes,Microsoft Word 2007+)
- [agent_tasks.json](agent_tasks.json) — 27 task 完整状态(13 unique agents)
- [report.json](report.json) — 报告 v=1 完整 dimensions 数组

## 整体结论
- ✅ A 阶段三层自动套件全绿,无回归
- ✅ B 阶段 8 步 UI walkthrough 全部通过,包括之前 fix-bug 修复的 Bug 1 在新数据集上**二次实战验证**
- ⚠️ 2 个非 blocker UI 文案缺口已登记
- 此次 walkthrough 也是新 CLAUDE.md L3 工具(Claude_in_Chrome)落地的首次"广度"实例
