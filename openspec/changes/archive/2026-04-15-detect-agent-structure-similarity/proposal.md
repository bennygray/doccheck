## Why

M3 第 4 个真实 Agent。execution-plan §3 C9 要求 `detect-agent-structure-similarity` 做三维度结构相似度检测(目录结构 / 字段结构 / 表单填充模式),覆盖 4 个典型场景 —— 尤其 Scenario 2"两份报价表填充结构一致(相同空值/相同合并单元格)"要求 cell 级精度,无法靠现有 `DocumentText.merged_text`(纯文本合并)实现。为此 C9 同时延伸 C5 parser-pipeline 持久化层:xlsx 解析结果除保留 `DocumentText`(相似度用)外,新增 `DocumentSheet` 存整表 rows 矩阵 + 合并单元格信息,为 C9 及后续报价类 Agent 提供 cell 级数据源。

## What Changes

### 检测层(C9 主体)

- 替换 `backend/app/services/detect/agents/structure_similarity.py::run()` 的 dummy 实现为真实三维度算法
- 新增子包 `backend/app/services/detect/agents/structure_sim_impl/`(预计 6~7 模块:`config.py` / `models.py` / `title_lcs.py` / `field_sig.py` / `fill_pattern.py` / `scorer.py` / `__init__.py`)
- **目录结构维度**:docx 两侧章节标题序列 LCS,归一化相似度 = `2 × LCS_len / (len_left + len_right)`;章节提取复用 C8 `section_sim_impl.chapter_parser.extract_chapters`(零改动 import)
- **字段结构维度**:xlsx 每 sheet 取列头行 hash + 每行非空列 bitmask 序列 + 合并单元格 ranges;三者分别计算 Jaccard/序列相似度,加权合并
- **表单填充模式维度**:xlsx 非空 cell 值类型 pattern 矩阵(数字/日期/文本)做 Jaccard
- **三维度聚合**:默认权重 `0.4 / 0.3 / 0.3`(目录/字段/填充)加权求和为 Agent 总分
- **preflight** 延用 C6 contract "双方有同角色文档",追加"至少一侧结构可提取"(docx 章节 ≥ MIN_CHAPTERS **或** xlsx sheet ≥ 1 有效行)
- **关键约束**:结构提取失败 → 该维度 skip,**不做 C8 式降级**(execution-plan §3 C9 兜底原文);3 维度全失败 → Agent 整体 skip `"structure_missing"`
- **LLM 不引入**:纯程序化(LCS/Jaccard/hash),不走 llm_judge 通道

### 数据层(C5 延伸)

- 新增 model `backend/app/models/document_sheet.py`:`DocumentSheet`(`id` / `bid_document_id` FK / `sheet_index` / `sheet_name` / `hidden` bool / `rows_json` JSONB / `merged_cells_json` JSONB / `created_at`)
- 新增 alembic 迁移 `backend/alembic/versions/0006_add_document_sheet.py`
- 扩展 `backend/app/services/parser/content/__init__.py` 的 xlsx 分支:保留写 `DocumentText`(供现有相似度 Agent 用),额外写 `DocumentSheet`(rows 矩阵 + 合并单元格 ranges 字符串列表)
- 新增一次性回填脚本 `backend/scripts/backfill_document_sheets.py`:幂等(已有 DocumentSheet 的 doc_id 跳过),扫描 `BidDocument.file_ext == ".xlsx" AND parse_status == "identified"` 重新 `extract_xlsx` 写入 DocumentSheet;手工触发,不进 migration

### 不动的东西

- registry / engine / judge / context / preflight_helpers / ProcessPoolExecutor 通道 —— 全保持
- C7 `text_sim_impl/` / C8 `section_sim_impl/`:**零改动**,仅 C9 子包 import 复用
- 其他 7 个 Agent 骨架:继续 dummy run(等 C10~C14)

## Capabilities

### New Capabilities

- 无(C9 不引入新 capability,只在既有 spec 追加 Req)

### Modified Capabilities

- `detect-framework`:新增 C9 `structure_similarity` Agent 的三维度算法 Req + preflight 追加 Req + 结构缺失 skip 兜底 Req + `DocumentSheet` 数据契约 Req + 环境变量 Req;删除 "10 Agent 骨架" 原 dummy scenario 中 `structure_similarity`(改为真实实现)
- `parser-pipeline`:新增 xlsx DocumentSheet 持久化 Req(rows_json + merged_cells_json)+ 回填脚本 Req(幂等 / 手工触发 / 错误隔离)

## Impact

### 代码

- 新增:`backend/app/models/document_sheet.py` / `backend/alembic/versions/0006_add_document_sheet.py` / `backend/app/services/detect/agents/structure_sim_impl/*.py`(~7 文件) / `backend/scripts/backfill_document_sheets.py`
- 修改:`backend/app/services/detect/agents/structure_similarity.py`(重写 `run()`) / `backend/app/services/parser/content/__init__.py`(xlsx 分支扩展) / `backend/app/models/__init__.py`(导出 DocumentSheet)
- 零改动:C7/C8 子包 / 10 Agent 注册框架 / engine / judge

### 数据库

- 新表 `document_sheet`(1 FK + 2 JSONB + 3 标量列)
- 无破坏性迁移;alembic 0006 单向 head,回滚 drop 表
- 已上传 xlsx 文档:需手工跑 `python -m scripts.backfill_document_sheets` 回填一次

### 依赖

- **零新增第三方依赖**:openpyxl(C5 已有)/ SQLAlchemy JSONB(C3 已有)

### 环境变量

- `STRUCTURE_SIM_MIN_CHAPTERS`(默认 3)——目录结构维度最少章节数
- `STRUCTURE_SIM_MIN_SHEET_ROWS`(默认 2)——字段/填充维度最少有效行数
- `STRUCTURE_SIM_WEIGHTS`(默认 "0.4,0.3,0.3")——三维度权重
- `STRUCTURE_SIM_FIELD_JACCARD_SUB_WEIGHTS`(默认 "0.4,0.3,0.3")——列头/bitmask/合并单元格子权重

### 测试

- L1:子包 6~7 模块单测(~25 用例)+ `test_structure_similarity_run.py`(~6 用例)+ DocumentSheet 持久化测试(~3 用例)+ 回填脚本幂等测试(~2 用例)
- L2:4 scenario E2E(目录一致命中 / 报价表填充结构一致命中 / 独立结构不误报 / 结构提取失败标"结构缺失")
- L3:延续 C5~C8 降级为手工凭证(Docker kernel-lock 未解),新增手工步骤写入 `e2e/artifacts/c9-YYYY-MM-DD/README.md`

### Follow-up(进 handoff §3)

- 合并单元格细粒度比对(目前只比 ranges 位置集合,未考虑合并后填充内容)
- `DocumentSheet.rows_json` 若遇巨型 xlsx(> 10k 行)JSONB 存储成本;C9 默认裁切 `MAX_ROWS_PER_SHEET=5000`,超出段落告警,根本解留更后
- L3 手工凭证补齐(Docker kernel-lock 依赖)
