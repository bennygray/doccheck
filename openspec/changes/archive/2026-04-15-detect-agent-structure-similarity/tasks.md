## 1. DocumentSheet 模型 + 迁移

- [x] 1.1 [impl] 新建 `backend/app/models/document_sheet.py`:`DocumentSheet` SQLAlchemy 模型(表名 `document_sheets` 复数;id / bid_document_id FK / sheet_index / sheet_name / hidden / rows_json JSON-variant / merged_cells_json JSON-variant / created_at);联合唯一 `(bid_document_id, sheet_index)`;不加 CASCADE
- [x] 1.2 [impl] `backend/app/models/__init__.py` 导出 `DocumentSheet`
- [x] 1.3 [impl] 新建 `backend/alembic/versions/0006_add_document_sheets.py`:CREATE TABLE + 索引 + 唯一约束;JSONB PG 变体;downgrade drop 表
- [x] 1.4 [impl] `alembic upgrade head` 本地验证迁移无报错
- [x] 1.5 [L1] `backend/tests/unit/test_document_sheet_model.py`:建模 + unique 约束 + JSONB roundtrip(3 用例,全绿)

## 2. xlsx_parser 扩展 merged_cells_ranges

- [x] 2.1 [impl] 修改 `backend/app/services/parser/content/xlsx_parser.py`:`SheetData` dataclass 追加 `merged_cells_ranges: list[str]` 字段(默认空 list)
- [x] 2.2 [impl] `extract_xlsx`:对每 ws 读 `ws.merged_cells.ranges`,`str(r)` 转字符串列表填 `merged_cells_ranges`;try/except 兜底
- [x] 2.3 [impl] 单 sheet extract 异常隔离时 `merged_cells_ranges` 默认 `[]`;既 frozen dataclass 加字段对 fill_price 等下游零破坏(只读 rows)
- [x] 2.4 [L1] `backend/tests/unit/test_parser_content_xlsx_merged_cells.py`:有合并 / 无合并 / 多 sheet 隔离(3 用例,全绿)

## 3. C5 content 层 xlsx 分支扩展

- [x] 3.1 [impl] 修改 `backend/app/services/parser/content/__init__.py` xlsx 分支:保留 DocumentText 写入,追加 DocumentSheet 写入;`_clean_prior_extraction` 同步清 DocumentSheet
- [x] 3.2 [impl] 引入 `STRUCTURE_SIM_MAX_ROWS_PER_SHEET` env(默认 5000):rows 超上限时截断 + `logger.warning`;**apply 期就地决策**:辅助 `_get_max_rows_per_sheet()` 放 `content/__init__.py` 内部(子包 `structure_sim_impl.config` 也会读同 env,两边独立 parse 不耦合)
- [x] 3.3 [L2] `backend/tests/e2e/test_parser_content_api.py` 扩展:`test_xlsx_persists_document_sheet` + `test_xlsx_truncates_oversized_sheet`(2 用例);`auth_fixtures._delete_all` 加 DocumentSheet(fixture 一致性修正)

## 4. 回填脚本

- [x] 4.1 [impl] `backend/scripts/__init__.py` 已存在,无需新建
- [x] 4.2 [impl] 新建 `backend/scripts/backfill_document_sheets.py`:async main;`_iter_targets` NOT EXISTS 过滤;单 doc 独立 session + try/except rollback + 日志;汇总 total/success/failed;退出码 0/1
- [x] 4.3 [impl] `--dry-run` option 实现(argparse):列目标 doc 数 + 每个 file_name,不写
- [x] 4.4 [L1] `backend/tests/unit/test_backfill_document_sheets.py`:幂等重跑 / 错误隔离 / dry-run(3 用例,全绿)

## 5. structure_sim_impl 子包骨架

- [x] 5.1 [impl] 新建 `backend/app/services/detect/agents/structure_sim_impl/__init__.py`
- [x] 5.2 [impl] `structure_sim_impl/config.py`:5 env 动态读;WEIGHTS / FIELD_SUB_WEIGHTS 复用 `_parse_triple_weights` helper;非法值 fallback + warning
- [x] 5.3 [impl] `structure_sim_impl/models.py`:5 dataclass(DirResult / SheetFieldResult / FieldSimResult / SheetFillResult / FillSimResult)+ AggregateResult
- [x] 5.4 [L1] `test_config.py`:defaults / env override / WEIGHTS 5 种非法值 parametrize / MAX_ROWS 非法 fallback(8 用例,全绿)

## 6. 目录结构维度(title_lcs)

- [x] 6.1 [impl] 新建 `structure_sim_impl/title_lcs.py`:`_normalize_title(s)` 5 PATTERN 序号剥离 + 空白全角去除 + 标点去除
- [x] 6.2 [impl] `_lcs_length(a, b)` 一维 DP 优化;`_lcs_matched_titles` 回溯取前 10 条匹配(用二维 DP 表)
- [x] 6.3 [impl] `async compute_directory_similarity(...) -> DirResult | None`:run_in_executor 走 `get_cpu_executor()`;章节数 < `config.min_chapters()` → None;空标题过滤后仍空 → 返 DirResult score=0
- [x] 6.4 [L1] `test_title_lcs.py`:归一化 9 pattern / LCS 4 案例 / 目录全同 / 归一化跨序号匹配 / 完全不同 / 章节不足 / 环境变量覆盖 / 部分重合(19 用例,全绿)

## 7. 字段结构维度(field_sig)

- [x] 7.1 [impl] 新建 `structure_sim_impl/field_sig.py`:`SheetInput` dataclass + `_extract_header_tokens`(归一化 ascii/保留中文)
- [x] 7.2 [impl] `_row_bitmask`:尾部连续 0 截掉(降低稀疏 sheet 干扰);`_cell_nonempty` 处理 "" 和 "   "
- [x] 7.3 [impl] `_jaccard_set` / `_jaccard_multiset` 独立 helper(Counter 交并);两侧全空时返 1.0(但被 min_rows 过滤拦住)
- [x] 7.4 [impl] `compute_field_similarity`:按 sheet_name 配对 + min_rows 过滤 + per_sheet 按 sub_score 降序截 top-5
- [x] 7.5 [L1] `test_field_sig.py`:14 用例(cell_nonempty / header 归一化 2 / bitmask / jaccard set/multiset / 完全相同 / 不同 header / sheet 名不重合 / 多 sheet max / min_rows / 空输入 / 子权重 env / top-5 截断)

## 8. 表单填充模式维度(fill_pattern)

- [x] 8.1 [impl] `fill_pattern.py`:`cell_type_pattern` 4 类(N/D/T/_),bool 归 T(开关非数值);ascii 数字+千分位+负号识别
- [x] 8.2 [impl] `_DATE_PATTERNS` 含 ISO + 中文 `年月日`;`_NUMBER_PATTERN` 千分位+小数+负号
- [x] 8.3 [impl] `compute_fill_similarity`:sheet 配对(同 field_sig)+ multiset Jaccard;sample_patterns 过滤全 '_' pattern(全空行无意义)
- [x] 8.4 [L1] `test_fill_pattern.py`:20 cell 分类 parametrize / row pattern / 完全相同 / 同结构异内容(关键场景)/ 完全异类型 / 名不重合 / 空 / min_rows / 全空 pattern 不入 sample / 多 sheet max(28 用例)

## 9. 三维度聚合(scorer)

- [x] 9.1 [impl] `scorer.py`:`aggregate_structure_score` 返 `AggregateResult`(score/participating/weights_used/is_ironclad)
- [x] 9.2 [impl] 参与维度原始权重归一化(`weighted_sum/total_w`);全 None → score=None;is_ironclad = 任一 sub ≥ 0.9 且 total ≥ 85
- [x] 9.3 [impl] `build_evidence_json` 构 design D9 schema(dimensions.<dim>.score/reason/per_sheet)
- [x] 9.4 [L1] `test_scorer.py`:全 3 参与 / 仅 2 重归一化 / 仅 1 / 全 None / ironclad 3 条件组合 / custom weights / evidence 3 dims / evidence with skip reasons / evidence agent skip(11 用例)

## 10. structure_similarity.py::run() 真实实现

- [x] 10.1 [impl] 重写 `structure_similarity.py`:import `structure_sim_impl` 子包;删除 `_dummy` 引用
- [x] 10.2 [impl] preflight:C6 原 + `bidders_share_role_with_ext({.docx})` 或 `({.xlsx})` 任一 → ok;都无 → skip "结构缺失"(新增 `_preflight_helpers.bidders_share_role_with_ext`)
- [x] 10.3 [impl] run() 流程:`asyncio.gather` 并行加载 docx_pair + xlsx_pair(新增 `loaders.py`)→ 三维度计算(目录走 CPU executor,字段/填充同步)→ `aggregate_structure_score` → `build_evidence_json` → PairComparison
- [x] 10.4 [impl] `loaders.load_docx_titles_pair` 复用 C8 `chapter_parser.extract_chapters`(零改 C8);`loaders.load_xlsx_sheets_pair` 读 `DocumentSheet` 转 `SheetInput`
- [x] 10.5 [impl] 3 维度全 None 时 PairComparison.score=0.0 哨兵 + evidence.participating_dimensions=[] + summary="结构缺失:<reasons>"(spec 已调整,AgentRunResult.score 类型保留 float)
- [x] 10.6 [L1] `tests/unit/services/detect/agents/test_structure_similarity_run.py`:preflight 3 路径 / 三维度全参与 / xlsx-only / docx-only / 全 skip / ironclad 触发(8 用例,全绿)

## 11. E2E 真实检测链路(L2)

- [x] 11.1 [impl] 新建 `backend/tests/e2e/test_detect_structure_similarity.py`:自包含 seed helper(`_seed_project` / `_seed_bidder` / `_add_docx_with_paras` / `_add_xlsx_with_sheets` / `_add_image`)
- [x] 11.2 [L2] Scenario 1 "目录完全一致命中":4 章节序列同 → dimensions.directory.score ≥ 0.9 + lcs_length == 4 + 总 score ≥ 60
- [x] 11.3 [L2] Scenario 2 "报价表填充结构一致命中":单 sheet 同结构 → dimensions.field_structure.score ≥ 0.8 + per_sheet.sub_score ≥ 0.9
- [x] 11.4 [L2] Scenario 3 "独立结构不误报":章节完全不同 + xlsx 异构 → score < 30 + is_ironclad=false
- [x] 11.5 [L2] Scenario 4 "结构缺失 preflight skip":仅图片共享角色 → preflight status=skip reason="结构缺失",无 PairComparison 行;run 级 all-None 已由 L1 `test_run_all_skipped_when_extraction_fails` 覆盖

## 12. 环境变量与文档

- [x] 12.1 [impl] `backend/README.md` 新增 "C9 detect-agent-structure-similarity 依赖" 段:5 env + DocumentSheet 延伸 + 回填脚本用法
- [x] 12.2 [impl] 5 env 由 `structure_sim_impl/config.py` + `content/__init__.py`(MAX_ROWS)+ `scripts/backfill_document_sheets.py`(MAX_ROWS)各自独立读取,不走 pydantic settings,便于 monkeypatch

## 13. L3 UI 验证(降级手工凭证)

- [x] 13.1 [L3] Docker kernel-lock 未解 → 手工降级(延续 C5~C8)
- [x] 13.2 [manual] `e2e/artifacts/c9-2026-04-15/README.md` 占位 + 3 张截图计划(启动检测 / 报告页三维度展开 / 回填脚本日志)+ `.gitignore` 加 c9-* 白名单
- [x] 13.3 [manual] 回填脚本手工执行延后到 kernel-lock 解除后(连同 L3 截图一起);pre-prod 无生产 xlsx 数据,不阻塞归档 — 记入 handoff follow-up

## 14. 自检与归档前校验

- [x] 14.1 [impl] `ruff check` C9 scope(structure_similarity.py + structure_sim_impl/ + document_sheet.py + backfill_document_sheets.py)全绿;`content/__init__.py` 有 2 条 pre-existing F401/E501 不属 C9 scope
- [x] 14.2 [impl] C7 `text_sim_impl/` + C8 `section_sim_impl/` + registry/engine/judge/context 零 diff 确认(git diff --stat 仅 `_preflight_helpers.py +26 行` 和 `structure_similarity.py +227 行`)
- [x] 14.3 [impl] `_dummy.py` 保留(7 Agent 仍用);structure_similarity.py 不再 import `_dummy`
- [x] 14.4 [impl] `openspec validate detect-agent-structure-similarity --strict` 通过
- [x] 14.5 跑 [L1][L2][L3] 全部测试,**550 全绿**(C9 新增 103 用例;C8 基线 448 → 550 = +102 含 E2E 新 2 用例);L3 延续手工凭证(kernel-lock 未解,占位 README 已建)
